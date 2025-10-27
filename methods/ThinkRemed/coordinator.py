import json
import time
import traceback

from methods.execution_agent import execute_playbook_and_get_response
from methods.ThinkRemed.probe_agent import get_probe_response
from methods.ThinkRemed.tools import print_playbook_function, probe_function
from methods.ThinkRemed.verification_agent import verify_status
from models.llm import chat_api

# Time to wait (in seconds) after playbook execution before verifying remediation success
WAIT_REME_TIME = 10
# Maximum number of remediation retries allowed (0 means no retries)
MAX_RETRY_TIME = 1


def remediate_failure(runtime_envs, namespace, root_cause, failure_category):
    """
    Orchestrates an LLM-driven remediation process using the ThinkRemed framework.
    The agent may iteratively probe the system state and refine its Ansible playbook until the failure is resolved or retries are exhausted.

    Args:
        runtime_envs (str): Contextual runtime information (e.g., metrics, logs, topology).
        namespace (str): Kubernetes namespace of the affected service.
        root_cause (str): Name of the service identified as the root cause.
        failure_category (str): Type of failure (e.g., "latency", "error_rate", "pod_crash").

    Returns:
        tuple: (conversation history as list of message dicts, number of remediation attempts made)
    """
    print("=" * 50)
    print(f"Start to remediate root cause: {root_cause}, failure category: {failure_category}")

    # Load Ansible inventory to provide infrastructure context to the LLM
    with open("inventory.ini", "r") as fr:
        inventory_content = fr.read()

    # Construct the initial system prompt with environment and task context
    root_prompt = f'''You are an experienced SRE managing a microservice system.
    A failure has occurred, and your task is to generate a final executable Ansible playbook based on the given root cause, failure category, and the probed information (executed by "ansible-playbook -i inventory.ini remediation.yml").
    The system will automatically execute the playbook and verify whether the failure has been successfully resolved.  
    [Attention] Please ensure that online services remain uninterrupted; restarting services should not be considered a primary strategy.
    {runtime_envs}
    The content of inventory.ini is {inventory_content}
    The current namespace is: {namespace}, failure root cause service is: {root_cause}, and the failure category is: {failure_category}.'''

    # Initialize the conversation history with the system role
    prompts = [{"role": "system", "content": root_prompt}]

    def get_playbook_with_probing():
        """
        Interactively engages the LLM in a loop:
        - If the LLM requests system probing (via 'probe' tool), execute the probe and feed results back.
        - If the LLM outputs a playbook (via 'print_playbook'), return it.
        - Continues until a playbook is produced or an error occurs.
        """
        nonlocal prompts
        while True:
            # Call LLM with available tools: playbook generation and system probing
            response_message, tools = chat_api(prompts, tools=[print_playbook_function, probe_function])
            if not tools:
                return ""

            # Case 1: LLM directly outputs a playbook
            if tools and tools[0]["function"]["name"] == "print_playbook":
                try:
                    tool_args_str = tools[0]["function"]["arguments"]
                    print(tool_args_str)
                    # Append raw tool output to conversation for auditability
                    prompts.append({"role": "assistant", "content": tool_args_str})
                    # Extract the YAML playbook code from structured JSON arguments
                    return json.loads(tool_args_str)["code"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Handle malformed or incomplete tool response
                    prompts.append({"role": "assistant", "content": "Error Code"})
                    return ""

            # Case 2: LLM requests one or more probes to gather system state
            for tool in tools or []:
                print("think:" + str(tool))
                try:
                    # Parse the requested probe commands
                    probe_commands = json.loads(tool["function"]["arguments"])["cmds"]
                    # Execute the probe and retrieve real-time system feedback
                    tool_result = get_probe_response(probe_commands)
                    # Record the probe result as an assistant message (function output)
                    prompts.append({"role": "assistant", "content": tool_result})

                    # Prompt the LLM to continue toward playbook generation
                    round_prompt = '''Please continue to generate executable Ansible playbook or get more information from the probe agent.'''
                    prompts.append({"role": "user", "content": round_prompt})
                except Exception:
                    # Silently skip malformed probe requests to avoid breaking the loop
                    pass

            # Loop continues until a playbook is generated

    # Attempt to generate the initial remediation playbook (with optional probing)
    try:
        playbook_code = get_playbook_with_probing()
    except Exception as e:
        traceback.print_exc()
        print(f"Failed to generate playbook: {e}")
        return False, -1

    # Encapsulate playbook execution and post-execution verification
    def execute_and_verify():
        """
        Executes the generated Ansible playbook and verifies whether the failure condition is resolved.
        """
        status, output = execute_playbook_and_get_response(playbook_code)
        if status:
            # Allow time for system to stabilize after remediation
            time.sleep(WAIT_REME_TIME)
            # Verify service health based on failure category and root cause label
            verify_status_result = verify_status(
                namespace=namespace,
                label=f"app={root_cause}",
                type=failure_category
            )
            return status, verify_status_result, output
        return status, False, output

    # Perform the first remediation attempt
    playbook_exec_status, status, output = execute_and_verify()

    # Log the execution outcome in the conversation history
    prompts.append({"role": "assistant", "content": f"playbook execution response: {output}"})

    # Retry loop: attempt remediation again if verification failed and retries remain
    try_time = 1
    while not status and try_time <= MAX_RETRY_TIME:
        # Inform the LLM that remediation failed and request a refined strategy
        retry_prompt = f'''The failure of online service has not yet been remediated.
        You may use the probe agent to further inspect the system state and generate a new Ansible playbook to attempt remediation again.
        The previous playbook execution returned: {playbook_exec_status}, output: {status}'''
        prompts.append({"role": "user", "content": retry_prompt})

        try:
            playbook_code = get_playbook_with_probing()
        except Exception as e:
            print(f"Retry failed to generate playbook: {e}")
            break

        # Execute the new playbook and verify again
        playbook_exec_status, status, output = execute_and_verify()
        try_time += 1

        # Record the latest execution result
        prompts.append({"role": "assistant", "content": f"playbook execution response: {output}"})

    # Return full interaction trace and number of attempts made
    return prompts, try_time

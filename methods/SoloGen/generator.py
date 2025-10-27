import json
import time

from methods.SoloGen.tools import print_playbook_function
from methods.execution_agent import execute_playbook_and_get_response
from models.llm import chat_api

# Time to wait after remediation execution before verification (in seconds)
WAIT_REME_TIME = 10
# Maximum number of retries allowed for remediation attempts (currently unused but reserved)
MAX_RETRY_TIME = 3


def remediate_failure(runtime_envs, namespace, root_cause, failure_category):
    """
    Generates and executes an Ansible playbook to remediate a diagnosed failure in a Kubernetes-based microservice environment.

    Args:
        runtime_envs (str): Runtime context or environment description (e.g., service topology, metrics).
        namespace (str): Kubernetes namespace where the failure occurred.
        root_cause (str): The service or component identified as the root cause.
        failure_category (str): High-level category of the failure (e.g., "latency", "error_rate", "resource_exhaustion").

    Returns:
        tuple: (prompts history, number of remediation attempts made)
    """
    print("=" * 50)
    print(f"Start to remediate root cause: {root_cause}, failure category: {failure_category}")

    # Load the Ansible inventory file content to provide context for playbook generation
    with open("inventory.ini", "r") as fr:
        inventory_content = fr.read()

    # Construct the initial system prompt with contextual information for the LLM
    root_prompt = f'''You are an experienced SRE managing a microservice system.
    A failure has occurred, and your task is to generate a final executable Ansible playbook based on the given root cause and failure category (executed by "ansible-playbook -i inventory.ini remediation.yml").
    The system will automatically execute the playbook and verify whether the failure has been successfully resolved.  
    [Attention] Please ensure that online services remain uninterrupted; restarting services should not be considered a primary strategy.
    {runtime_envs}
    The content of inventory.ini is {inventory_content}
    The current namespace is: {namespace}, failure root cause service is: {root_cause}, and the failure category is: {failure_category}.'''

    # Initialize conversation history with the system prompt
    prompts = [{"role": "system", "content": root_prompt}]

    # Invoke the LLM with a function-calling tool to generate the playbook
    _, tools = chat_api(prompts, tools=[print_playbook_function])

    playbook_code = ""
    # Check if the LLM responded with a valid tool call to print_playbook
    if tools and tools[0]["function"]["name"] == "print_playbook":
        try:
            # Append the LLM's raw tool arguments to the conversation history for traceability
            tool_arguments_str = tools[0]["function"]["arguments"]
            prompts.append({"role": "assistant", "content": tool_arguments_str})
            print(tool_arguments_str)

            # Parse the JSON-formatted arguments and extract the playbook code
            playbook_code = json.loads(tool_arguments_str)["code"]
        except (json.JSONDecodeError, KeyError, TypeError):
            # Handle malformed or unexpected tool response
            prompts.append({"role": "assistant", "content": "Error Code"})
            playbook_code = ""

    # Execute the generated Ansible playbook in the target environment
    execute_playbook_and_get_response(playbook_code)

    # Allow time for the remediation to take effect before verification
    time.sleep(WAIT_REME_TIME)

    # Return the full prompt history and the count of remediation attempts (currently always 1)
    return prompts, 1

import subprocess
import sys
import os
import signal


def execute_playbook_and_get_response(playbook: str, timeout: int = 300):
    """
    Execute a given Ansible playbook and return its execution result.

    Args:
        playbook (str): YAML content of the Ansible playbook.
        timeout (int): Maximum execution time in seconds (default: 300).

    Returns:
        (bool, str): A tuple where:
            - bool indicates whether the execution was successful.
            - str contains stdout (on success) or detailed error output (on failure).

    Raises:
        RuntimeError: If file writing or execution fails unexpectedly.
    """

    playbook_file = "remediation.yml"
    inventory_file = "inventory.ini"

    # Step 1: Write playbook content to a file
    try:
        with open(playbook_file, "w") as f:
            f.write(playbook)
        print(f"✅ Playbook written to: {playbook_file}", file=sys.stderr)
    except Exception as e:
        raise RuntimeError(f"❌ Failed to write playbook file {playbook_file}: {e}")

    # Step 2: Prepare ansible-playbook command
    cmd = ["ansible-playbook", "-i", inventory_file, playbook_file]
    print(f"🚀 Executing command: {' '.join(cmd)}", file=sys.stderr)

    try:
        # Start a new process group so we can kill all child processes if it hangs
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True  # Important for killing the whole group
        )

        # Wait for the process to complete with timeout
        stdout, stderr = proc.communicate(timeout=timeout)

        if proc.returncode == 0:
            print("✅ Playbook executed successfully.", file=sys.stderr)
            return True, stdout.strip()
        else:
            error_msg = (
                f"⚠️ Playbook execution failed (exit code {proc.returncode})\n"
                f"STDOUT:\n{stdout.strip()}\n\nSTDERR:\n{stderr.strip()}"
            )
            print(error_msg, file=sys.stderr)
            return False, error_msg

    except subprocess.TimeoutExpired:
        # Kill the entire process group
        print(f"⏰ Playbook execution exceeded {timeout}s — force killing...", file=sys.stderr)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception as kill_err:
            print(f"⚠️ Failed to terminate process group: {kill_err}", file=sys.stderr)
        stdout, stderr = proc.communicate()
        error_msg = (
            f"⏰ Ansible playbook timed out after {timeout}s.\n"
            f"Partial STDOUT:\n{stdout.strip()}\n\nPartial STDERR:\n{stderr.strip()}"
        )
        return False, error_msg

    except FileNotFoundError:
        error_msg = "❌ 'ansible-playbook' command not found. Please ensure Ansible is installed and available in PATH."
        print(error_msg, file=sys.stderr)
        return False, error_msg

    except Exception as e:
        error_msg = f"⚠️ Unexpected error during playbook execution: {e}"
        print(error_msg, file=sys.stderr)
        return False, error_msg
import subprocess
import sys
from typing import Union, List


def get_probe_response(
        cmds: Union[str, List[str]],
        timeout: int = 10,
        check: bool = False,
        verbose: bool = False
) -> str:
    """
    Executes system command(s) and returns the combined standard output.

    Args:
        cmds (str or List[str]): The command(s) to execute. Can be a single string (e.g., "ls -l")
                                 or a list of strings (e.g., ["kubectl", "get", "pods"]).
                                 If a string contains semicolons (';'), it will be split into multiple commands.
        timeout (int): Maximum time (in seconds) to wait for each command to complete. Default is 10 seconds.
        check (bool): If True, raises an exception on command failure or timeout.
                      If False (default), captures and returns error details as part of the output string.
        verbose (bool): If True, prints debug information (e.g., command being run, success/failure) to stderr.

    Returns:
        str: A concatenated string of results for all executed commands, formatted as:
             "command: <cmd>\nresponse: <output or error>\n".
             On success, includes stdout.
             On failure (and check=False), includes stderr and error context.

    Raises:
        RuntimeError: If `check=True` and a command fails (non-zero exit code).
        subprocess.TimeoutExpired: If `check=True` and a command exceeds the timeout.
        FileNotFoundError: If `check=True` and the command executable is not found.
    """
    # Normalize input command(s) into a list of individual commands
    if isinstance(cmds, str) and ";" in cmds:
        cmd_list = cmds.split(";")
    else:
        cmd_list = [cmds] if isinstance(cmds, str) else cmds

    outputs = ""
    for cmd in cmd_list:
        if verbose:
            print(f"Executing command: {cmd}", file=sys.stderr)

        try:
            # Execute the command using shell=True to support pipes, redirections, etc.
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if verbose:
                    print(f"Command succeeded: return code={result.returncode}", file=sys.stderr)
                outputs += "command:" + cmd + "\nresponse:" + output + "\n"
            else:
                # Construct detailed error message including stdout and stderr
                error_msg = (
                    f"Command failed (command: {cmd})\n"
                    f"STDOUT:\n{result.stdout.strip()}\n"
                    f"STDERR:\n{result.stderr.strip()}"
                )
                if verbose or not check:
                    print(error_msg, file=sys.stderr)
                if check:
                    raise RuntimeError(error_msg)
                outputs += error_msg + "\n"

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout} seconds:\n{cmd}"
            if verbose or not check:
                print(error_msg, file=sys.stderr)
            if check:
                raise  # Re-raise the original TimeoutExpired exception
            outputs += "command:" + cmd + "\nresponse: time out\n"

        except FileNotFoundError as e:
            error_msg = f"Command not found: {cmd}. Please ensure the executable is installed and in PATH.\nError: {e}"
            if verbose or not check:
                print(error_msg, file=sys.stderr)
            if check:
                raise
            outputs += "command:" + cmd + "\nresponse: command not found\n"

        except Exception as e:
            error_msg = f"Unexpected error while executing command: {e}\nCommand: {cmd}"
            if verbose or not check:
                print(error_msg, file=sys.stderr)
            if check:
                raise
            outputs += "command:" + cmd + "\nresponse: unknown error\n"

    return outputs
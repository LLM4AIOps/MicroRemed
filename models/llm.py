from argparse import Namespace

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from config import get_config, set_config
from concurrent.futures import ThreadPoolExecutor
import os

api_key = os.getenv("LLM_API_KEY")
if not api_key:
    raise ValueError("LLM_API_KEY environment variable is not set!")

TOOL_CALL_PROMPT = '''"{prompt_message}\n"
    "You have access to the following tools:\n{tool_text}\n"
    "Use the following format if using a tool:\n"
    "```\n"
    "Action: tool name (one of [{tool_names}])\n"
    "Action Input: the input to the tool, in a JSON format representing the kwargs "
    """(e.g. ```{{"input": "hello world", "num_beams": 5}}```)\n"""
    "```\n"
'''


def get_tool_names(tools):
    names = []
    for tool in tools:
        names.append(tool["function"]["name"])
    return names


def get_tool_from_content(content, tool_names):
    tools = []
    lines = content.split("\n")
    name = None
    for line in lines:
        if line.startswith("Action: "):
            name = line[len("Action: "):]
        elif line.startswith("Action Input: "):
            arguments = line[len("Action Input: "):]
            if name in tool_names:
                tools.append({
                    "function": {
                        "name": name,
                        "arguments": arguments
                    }
                })
    return tools


import warnings

warnings.filterwarnings("ignore")

import json


def parse_streamed_response(stream_response):
    """
    Parses a Server-Sent Events (SSE) streamed response from an LLM API,
    aggregates delta updates, and returns the final assistant message as a dictionary.

    The message may contain either regular text content or tool calls (or both),
    reconstructed from incremental chunks in the stream.

    Args:
        stream_response: A streaming response object (e.g., from requests) that yields SSE lines.

    Returns:
        dict: A complete assistant message with the following structure:
            {
                "role": "assistant",
                "content": str or None,
                "tool_calls": list of tool call objects (each with id, type, and function)
            }
    """
    full_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": []
    }

    # Temporary storage for tool calls, keyed by their index to support parallel tool invocations
    current_tool_calls = {}

    for line in stream_response.iter_lines():
        if not line:
            continue

        if line.startswith('data: '):
            data_str = line[6:]  # Strip the "data: " prefix
            if data_str.strip() == '[DONE]':
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue  # Skip malformed JSON lines

            # Skip chunks without choices
            if 'choices' not in chunk or not chunk['choices']:
                continue

            delta = chunk['choices'][0]['delta']

            # Accumulate content (may be null in tool-use scenarios)
            if 'content' in delta and delta['content'] is not None:
                full_message['content'] += delta['content']

            # Process incremental tool_call updates
            if 'tool_calls' in delta and delta['tool_calls']:
                for tool_call_chunk in delta['tool_calls']:
                    index = tool_call_chunk['index']

                    # Initialize a new tool call entry if not already present
                    if index not in current_tool_calls:
                        current_tool_calls[index] = {
                            "id": tool_call_chunk.get("id"),
                            "type": tool_call_chunk.get("type", "function"),
                            "function": {
                                "name": "",
                                "arguments": ""
                            }
                        }

                    func = current_tool_calls[index]["function"]
                    if "function" in tool_call_chunk:
                        func_chunk = tool_call_chunk["function"]
                        # Set function name (usually appears in the first chunk)
                        if "name" in func_chunk and func_chunk["name"]:
                            func["name"] = func_chunk["name"]
                        # Append incremental arguments (streamed as JSON fragments)
                        if "arguments" in func_chunk and func_chunk["arguments"]:
                            func["arguments"] += func_chunk["arguments"]

    # Convert the indexed tool calls into an ordered list
    if current_tool_calls:
        full_message['tool_calls'] = [
            current_tool_calls[i] for i in sorted(current_tool_calls.keys())
        ]
        # Align with non-streaming API format: set content to None if empty and tool_calls exist
        if full_message['content'] == "":
            full_message['content'] = None
    # If no tool calls, keep content as-is (even if empty string)

    return full_message


def chat_api(prompts, tools):
    model = get_config().model
    if "claude" in model:
        llm_client = LLMClient(
            api_url="https://api.anthropic.com/v1/messages",
            api_key=api_key
        )
    elif "gpt" in model:
        llm_client = LLMClient(
            api_url="https://api.openai.com/v1/chat/completions",
            api_key=api_key
        )
    elif "qwen" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    elif "Kimi" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    elif "llama" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    elif "deepseek" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    elif "glm" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    elif "qwq" in model:
        llm_client = LLMClient(
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=api_key
        )
    else:
        llm_client = LLMClient(
            api_url="http://localhost:8000/v1/chat/completions",
            api_key="s"
        )
    response = llm_client.generate(prompts, tools)
    return response


class LLMClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    @retry(
        stop=stop_after_attempt(1),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def generate(self, prompts: list, tools):
        model = get_config().model
        max_retry_time = 1
        retry_time = max_retry_time
        while retry_time >= 0:
            if tools:
                if 'claude' in model:
                    payload = {
                        "model": model,
                        "messages": prompts,
                        "max_tokens": 8192,
                        "tools": tools,
                        "tool_choice": {
                            "type": "any"
                        }
                    }
                elif 'gpt' in model:
                    payload = {
                        "model": model,
                        "messages": prompts,
                        "tools": tools,
                        "tool_choice": "required"
                    }
                elif 'qwen' in model or 'qwq' in model or 'glm' in model:
                    payload = {
                        "model": model,
                        "messages": prompts,
                        "tools": tools,
                        "max_tokens": 1024,
                        "stream": False,
                        "enable_thinking": False
                    }
                    if 'qwq' in model or 'glm' in model:
                        payload["stream"] = True
                else:
                    if retry_time == max_retry_time:
                        prompts[-1]["content"] = TOOL_CALL_PROMPT.format(
                            tool_text=json.dumps(tools),
                            tool_names=",".join(get_tool_names(tools)),
                            prompt_message=prompts[-1]["content"])
                    payload = {
                        "model": model,
                        "messages": prompts
                    }
            else:
                payload = {
                    "model": model,
                    "messages": prompts,
                    "max_tokens": 8192,
                }

            def _do_request():
                with httpx.Client() as client:
                    return client.post(
                        self.api_url,
                        headers=self.headers,
                        json=payload,
                        timeout=httpx.Timeout(connect=10, read=120, write=10, pool=60)
                    )

            try:
                with ThreadPoolExecutor() as executor:
                    future = executor.submit(_do_request)
                    response = future.result(timeout=300)
                    response.raise_for_status()
            except Exception as e:
                print(e)
                retry_time -= 1
                continue
            if 'gpt' in model:
                return_message = response.json()['data']['response']['choices'][0]['message']
                if 'tool_calls' in return_message:
                    return return_message['content'], return_message['tool_calls']
                retry_time -= 1
                if retry_time == 0:
                    return "", []
            elif 'claude' in model:
                content = response.json()
                res_tools = []
                if content['stop_reason'] == 'tool_use':
                    for tool in content['content']:
                        res_tools.append({
                            'function': {
                                'name': tool['name'],
                                'arguments': tool['input']
                            }
                        })
                if len(res_tools) > 0:
                    return content, res_tools
                retry_time -= 1
                if retry_time == 0:
                    return "", []
            elif 'qwen' in model or 'qwq' in model or 'glm' in model:
                if payload["stream"]:
                    full_message = parse_streamed_response(response)
                    if 'tool_calls' in full_message and full_message['tool_calls']:
                        return "", full_message['tool_calls']
                    retry_time -= 1
                    if retry_time == 0:
                        return "", []
                else:
                    return_message = response.json()['choices'][0]['message']
                    if 'tool_calls' in return_message:
                        return "", return_message['tool_calls']
                    retry_time -= 1
                    if retry_time == 0:
                        return "", []
            else:
                content = response.json()['choices'][0]['message']['content']
                res_tools = get_tool_from_content(content, get_tool_names(tools))
                if res_tools:
                    return content, res_tools
                retry_time -= 1
                if retry_time == 0:
                    return "", []
        return "", []


if __name__ == '__main__':
    # model = "claude-3-5-sonnet-20241022-X"
    # model = "gemini-1.5-pro-latest"
    # model = "claude-3-5-sonnet-latest"
    # model = "qwen3-coder-flash"
    # model = "gpt-4o"
    # model = "Gemma-2-9B"
    # model = "Llama-3_1-70B"
    # model = "QwQ-32B"

    # model = "qwen-plus"
    # model = "qwen-flash"
    # model = "qwq-32b"
    model = "glm-4.5"
    # model = "deepseek-v3.2-exp"
    # model = "Moonshot-Kimi-K2-Instruct"
    # model = "qwen3-235b-a22b"
    # model = "qwen3-next-80b-a3b-instruct"
    # model = "qwen3-next-80b-a3b-instruct"
    set_config(Namespace(model=model))
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Useful tool to get current time",
                "parameters": {}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Useful tool to get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City ..."
                        }
                    }
                },
                "required": [
                    "location"
                ]
            }
        }
    ]
    claude_tools = [
        {
            "name": "get_current_weather",
            "description": "Useful tool to get current weather",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City ..."
                    }
                },
                "required": [
                    "location"
                ]
            },
        }
    ]
    if "claude" in model:
        print(chat_api([{
            'role': 'user', 'content': "What's London's weather?"
        }], claude_tools))
    else:
        print(chat_api([{
            'role': 'user', 'content': "What's London's weather?"
        }], tools))

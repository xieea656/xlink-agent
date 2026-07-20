"""agent的工具列表与函数集"""
from rich.console import Console
import os , json , subprocess , requests
from config import resolve_credential
MAX_OUTPUT_CHARS = 10000
BASH_TIMEOUT = 30
console = Console()
def read_file(path: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """读文件工具"""
    real_path = os.path.realpath(os.path.expanduser(path))
    blacklist = [os.path.expanduser("~/.config/myagent")]
    for blocked in blacklist:
        if real_path.startswith(blocked):
            return f"Error:无权读取此文件"
    if os.path.isdir(path):
        return f"Error:'{path}' 是一个目录,无法读取"
    try:
        with open(path, "rb") as f: raw = f.read()
    except FileNotFoundError:
        return f"Error:文件 '{path}' 不存在"
    except PermissionError:
        return f"Error:没有权限读取文件 '{path}'"
    except IsADirectoryError:
        return f"Error:'{path}' 是一个目录,无法读取"
    except OSError as e:
        return f"Error:读取文件 '{path}' 时发生错误: {e}"
    if b"\x00" in raw:
        return f"Error:'{path}' 是二进制文件,无法读取"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    except Exception as e:
        return f"Error:读取文件 '{path}' 时发生错误: {e} 未知的编码"
    if len(text) > max_chars: text = text[:max_chars] + f"\n\n[truncated - 显示了 {max_chars} / 共 {len(text)} 字符]"
    return text
def run_bash(command: str, timeout: int = BASH_TIMEOUT, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """bash工具"""
    console.print(f"\n[tool: run_bash] pending command:\n  $ {command}")
    try:
        answer = input(" 是否允许执行? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):     
        answer = ""
    if answer not in ("y", "yes"):
        return "Error:请求被用户拒绝"
    try:
        result = subprocess.run(
        command,
        shell=True,          
        capture_output=True,  
        text=True,            
        timeout=timeout,      
        )
    except subprocess.TimeoutExpired: return f"Error:命令超时({timeout}s)"
    except Exception as e:return f"Error:executing command: {e}"
    output = result.stdout or ""
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if not output.strip():
        output = "(无输出)"
    if len(output) > max_chars:
        output = output[:max_chars] + f"\n\n[truncated - showed {max_chars} of {len(output)} chars]"
    return f"[exit code: {result.returncode}]\n{output}"
def write_file(path: str,content: str) -> str:
    """写文件工具"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入文件: {path} ({len(content)} 字符)"
    except Exception as e:
        return f"Error:写入文件 '{path}' 时发生错误: {e}"

ANYSEARCH_ENDPOINT = "https://api.anysearch.com/mcp"

def _call_anysearch(tool_name: str, arguments: dict, api_key=None) -> str:
    """调用 AnySearch JSON-RPC API"""
    if api_key is None:
        api_key = resolve_credential("anysearch")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    try:
        resp = requests.post(ANYSEARCH_ENDPOINT, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return f"Error: 搜索请求失败: {e}"
    data = resp.json()
    if "error" in data:
        return f"Error: API 错误: {data['error'].get('message', str(data['error']))}"
    result = data.get("result", {})
    content = result.get("content", [])
    for item in content:
        if item.get("type") == "text":
            return item.get("text", "")
    return json.dumps(result, indent=2, ensure_ascii=False)

def search_web(query: str, max_results: int = 5,_credential=None) -> str:
    """搜索网页工具"""
    if max_results < 1:
        max_results = 1
    if max_results > 20:
        max_results = 20
    return _call_anysearch("search", {"query": query, "max_results": max_results}, _credential)

def show_tools() -> str:
    """返回人类可读的工具列表 + 一行说明。"""
    lines = ["可用工具:"]
    for spec in TOOL_SPECS:
        fn = spec["function"]
        desc = fn["description"].split(". ")[0]   
        lines.append(f"  {fn['name']:<10} - {desc}")
    return "\n".join(lines)
def call_tool(tool_call):
    name = tool_call.function.name
    raw  = tool_call.function.arguments
    args = json.loads(raw)
    return dispatch_tool(name, args)
def call_tool_dict(call) -> str :
    """流式累积出的 tool_call(dict) -> 执行。适配 _stream_completion 返回格式。"""
    name = call["function"]["name"]
    raw = call["function"]["arguments"] or "{}"
    try:
          args = json.loads(raw)                
    except json.JSONDecodeError as e:
          return f"Error: invalid JSON for '{name}': {e}"
    return dispatch_tool(name, args)
def dispatch_tool(name,args):
    """执行工具：先解析凭证再调用 handler"""
    handler = TOOL_HANDLERS.get(name)
    spec = None
    if not handler :
        return "Error:未找到工具"
    for s in TOOL_SPECS:
        if s["function"]["name"] == name:
            spec = s
            break
    if spec and "credential" in spec:
        cred_name = spec["credential"]
        cred_value = resolve_credential(cred_name)
        if cred_value:
            args["_credential"] = cred_value
    try:
        return str(handler(**args))
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件的工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读的文件的绝对路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "执行 shell 命令(需用户确认)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件(覆盖已存在的文件)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要写入的文件路径"},
                    "content": {"type": "string", "description": "要写入的文件内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enter_plan_mode",
            "description": "当任务复杂需要先规划再执行时，进入计划模式",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type" : "function" ,
        "function" : {
            "name" : "search_web",
            "description" : "搜索网页，获取实时信息。支持一般搜索和垂直领域搜索",
            "parameters" : {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5，最大20"}
                },
                "required": ["query"]
            },
            "credential": "anysearch"
        }
    },
]

LOW_TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件的工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读的文件的绝对路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enter_plan_mode",
            "description": "当任务复杂需要先规划再执行时，进入计划模式",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索网页，获取实时信息。支持一般搜索和垂直领域搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5，最大20"}
                },
                "required": ["query"]
            },
            "credential": "anysearch"
        }
    },
]

TOOL_HANDLERS = {
    "read_file": read_file,
    "run_bash": run_bash,
    "write_file": write_file,
    "search_web": search_web,
}

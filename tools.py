"""agent的工具列表与函数集"""
import os , json , subprocess
MAX_OUTPUT_CHARS = 10000
BASH_TIMEOUT = 30
def read_file(path: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """读文件工具"""
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
    print(f"\n[tool: run_bash] pending command:\n  $ {command}")
    try:
        answer = input(" 是否允许执行? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):     # 非交互 -> 拒绝
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
def dispatch_tool(name,args):
    handler = TOOL_HANDLERS.get(name)
    if not handler :
        return "Error:未找到工具"
    try:
        return str(handler(**args))
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
TOOL_HANDLERS = {
      "read_file": read_file,
      "run_bash" : run_bash,
  }
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
                          "description": "要读的文件的绝对路径,例如 '/home/xieea/coding/myagent/main.py'"
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
  }
]
        
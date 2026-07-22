"""agent的工具列表与函数集"""
from rich.console import Console
import os , json , subprocess , requests ,re ,datetime
from zoneinfo import ZoneInfo, available_timezones
from config import resolve_credential, load_all_credentials
from log import read_line
MAX_OUTPUT_CHARS = 10000
BASH_TIMEOUT = 30
console = Console()
def read_file(path: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """读文件工具"""
    console.print(f"\n[tool: read_file] 读取: {path}")
    real_path = os.path.realpath(os.path.expanduser(path))
    blacklist = [os.path.expanduser("~/.config/myagent")]
    for blocked in blacklist:
        if real_path.startswith(blocked):
            return f"Error:无权读取此文件"
    if os.path.basename(real_path) == ".env":
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
        ext = os.path.splitext(path)[1].lower()
        MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
                          ".mp4", ".avi", ".mov", ".mkv", ".webm",
                          ".mp3", ".wav", ".flac", ".ogg", ".m4a"}  
        if ext in MEDIA_EXTENSIONS:
            return _media_metadata(real_path)
        else:
            return f"[binary file: {len(raw)} bytes, 文件: {os.path.basename(path)}]"
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
    creds = load_all_credentials()
    used = re.findall(r"\$CRED_([A-Z_]+)", command)
    env = os.environ.copy()
    for cred_name in used:
        key_in_yaml = cred_name.lower()
        if key_in_yaml in creds:
            env["CRED_" + cred_name] = creds[key_in_yaml]
    try:
        result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
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
    for cred_name in used:                                      
        key_in_yaml = cred_name.lower()                         
        val = creds.get(key_in_yaml)                            
        if val and len(val) > 4:                                
            output = output.replace(val, "***")
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
def classify(name, args):
    low_names = {s["function"]["name"] for s in LOW_TOOL_SPECS}
    if name in low_names:
        return "low"
    danger = [
          r"rm\s+(-[a-z]*r[a-z]*f?|-[a-z]*f[a-z]*r?)\s+(/|~|\*)(?=\s|\"|$)",
          r"mkfs", r"dd\s+.*of=/dev/", r":\(\)\{\s*:\|:&\s*\};:",
          r">\s*/dev/sd[a-z]", r"chmod\s+-R\s+777\s+/",
    ]
    text = json.dumps(args, ensure_ascii=False)
    for pat in danger:
        if re.search(pat, text):
            return "high"
    return "medium"
def _ask_user(name, risk):
    ans = input(f"允许执行 {name}? (y/N)").strip().lower()
    return {"decision":"allow" if ans=="y" else "deny",
            "risk":risk,"reason":"用户"+("同意" if ans=="y" else "拒绝")}
def _check_permission(name,args):
    risk = classify(name, args)         
    if risk == "low":  return {"decision":"allow","risk":risk,"reason":"低风险放行"}
    if risk == "high": return {"decision":"deny", "risk":risk,"reason":"高危拦截"}
    return _ask_user(name, risk)  
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
    if name == "run_bash":
        risk = classify(name, args)
        if risk == "high":
            return f"权限拒绝：高危拦截"
    else:
        perm = _check_permission(name, args)
        if perm["decision"] == "deny":
            return f"权限拒绝：{perm['reason']}"
    try:
        return str(handler(**args))
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
def _media_metadata(path):
    size = os.path.getsize(path)
    size_str = f"{size/1024:.0f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
    result = subprocess.run(["file", "-b", path], capture_output=True, text=True,env={"LC_ALL": "C"})
    file_info = result.stdout.strip()
    duration = ""
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
            "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=10)
        if r.stdout.strip():
            secs = float(r.stdout.strip())
            duration = f", {secs:.0f}s" if secs < 60 else f", {secs/60:.0f}m{secs%60:.0f}s"
    except : pass
    return f"[media: {file_info}{duration}, {size_str}, 文件:{os.path.basename(path)}]"
def timezone_convert(to_tz, from_tz="Asia/Shanghai", time_str=None):
    if time_str is None:
        dt = datetime.datetime.now()
    else:
        dt = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    dt = dt.replace(tzinfo=ZoneInfo(from_tz))
    target = dt.astimezone(ZoneInfo(to_tz))
    return target.strftime("%Y-%m-%d %H:%M:%S %Z")
def timezone_list(query=None):
    timezones = sorted(available_timezones())
    if query:
        timezones = [t for t in timezones if query.lower() in t.lower()]
    return "\n".join(timezones[:50])
def read_log_line(log_ref, start_line=None, end_line=None):
    """按 log 引用读工具日志全文。log_ref 格式: 2026-07-22:15 或 log:2026-07-22:15"""
    try:
        parts = log_ref.replace("log:", "").split(":")
        date, line_num = parts[0], parts[1]
        entry = read_line(date, int(line_num), start_line, end_line)
        if entry:
            return json.dumps(entry, ensure_ascii=False, indent=2)
        return "Error: 未找到日志记录"
    except Exception as e:
        return f"Error: 读取日志失败: {e}"

def edit_file(path: str, old_string: str, new_string: str) -> str:
    """在文件中搜索 old_string 并替换为 new_string（精确匹配，只替换第一次出现）"""
    real_path = os.path.realpath(os.path.expanduser(path))
    if os.path.basename(real_path) == ".env":
        return "Error: 无权编辑此文件"
    try:
        with open(real_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: 文件 '{path}' 不存在"
    except Exception as e:
        return f"Error: 读取文件失败: {e}"
    if old_string not in content:
        return "Error: 未找到匹配的 old_string"
    new_content = content.replace(old_string, new_string, 1)
    with open(real_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"已替换 1 处: {path}"

def search_files(pattern: str, path: str = ".", glob: str = None) -> str:
    """在目录中搜索匹配 pattern 的文本内容（grep 包装）"""
    real_path = os.path.realpath(os.path.expanduser(path))
    cmd = ["grep", "-n", "--color=never", "-r", pattern, real_path]
    if glob:
        cmd.extend(["--include", glob])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "Error: 搜索超时"
    if result.returncode != 0 and not result.stdout:
        return "(无匹配)"
    output = result.stdout or ""
    if len(output) > 5000:
        output = output[:5000] + f"\n\n[truncated - 显示了 5000 / 共 {len(output)} 字符]"
    return output

def list_files(path: str = ".", pattern: str = None) -> str:
    """列出目录下的文件和子目录，可选 glob 模式过滤"""
    real_path = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(real_path):
        return f"Error: '{path}' 不是目录"
    import glob as glob_mod
    if pattern:
        matches = glob_mod.glob(os.path.join(real_path, pattern), recursive=True)
        base = real_path
    else:
        try:
            matches = [os.path.join(real_path, f) for f in os.listdir(real_path)]
        except PermissionError:
            return f"Error: 没有权限读取目录 '{path}'"
        base = real_path
    lines = []
    for f in sorted(matches):
        if os.path.isdir(f):
            lines.append(os.path.relpath(f, base) + "/")
        else:
            try:
                size = os.path.getsize(f)
                lines.append(f"{os.path.relpath(f, base)}  ({size} bytes)")
            except OSError:
                lines.append(os.path.relpath(f, base) + "  (?)")
    if len(lines) > 200:
        lines = lines[:200] + [f"... 还有 {len(lines)-200} 项"]
    return "\n".join(lines)

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
    {
        "type": "function",
        "function": {
            "name": "timezone_convert",
            "description": "时区转换。把时间从一个时区转到另一个时区。不传 time_str 则用当前时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_tz": {"type": "string", "description": "目标时区，如 America/New_York"},
                    "from_tz": {"type": "string", "description": "源时区，默认 Asia/Shanghai"},
                    "time_str": {"type": "string", "description": "要转换的时间，格式 YYYY-MM-DD HH:MM，不传则用当前时间"}
                },
                "required": ["to_tz"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "timezone_list",
            "description": "列出可用时区，可选按关键词筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "筛选关键词，如 Asia、America"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_log_line",
            "description": "按 log 引用读取工具调用的完整结果。工具结果以 L2 简略格式返回时，用此工具取全文。log_ref 格式见 L2 结果中的 log:日期:行号",
            "parameters": {
                "type": "object",
                "properties": {
                    "log_ref": {"type": "string", "description": "日志引用，格式 日期:行号，如 2026-07-22:15"},
                    "start_line": {"type": "integer", "description": "可选，起始行号（从1开始）"},
                    "end_line": {"type": "integer", "description": "可选，结束行号"}
                },
                "required": ["log_ref"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "在文件中搜索 old_string 并替换为 new_string，精确匹配，只替换第一次出现",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原文（精确匹配）"},
                    "new_string": {"type": "string", "description": "替换后的新内容"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "在目录中搜索匹配 pattern 的文本内容（grep 包装）",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索关键词或正则"},
                    "path": {"type": "string", "description": "搜索目录，默认当前目录"},
                    "glob": {"type": "string", "description": "文件类型过滤，如 *.py"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录下的文件和子目录，可选 glob 模式过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录"},
                    "pattern": {"type": "string", "description": "glob 过滤模式，如 *.py、**/*.md"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "管理工作记忆。工作记忆不会被压缩，AI 可写入、删除、列出事实。用于记录重要结论、偏好、待办，供后续对话参考",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string", "enum": ["add", "remove", "list", "clear"],
                        "description": "add=写入, remove=删除, list=列出, clear=清空"
                    },
                    "fact": {"type": "string", "description": "事实内容（add/remove 时必填）"},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"], "description": "重要性（add 时可选，默认 medium）"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "store_tool_result",
            "description": "存储重要工具调用的完整回复到工具存储区。与工作记忆独立，不会被压缩。提供 log_ref 时 Agent 自动读取，无需手动传 content",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string", "enum": ["store", "remove", "list", "clear"],
                        "description": "store=存储, remove=删除, list=列出所有键, clear=清空"
                    },
                    "key": {"type": "string", "description": "存储键名（store/remove 时必填）"},
                    "content": {"type": "string", "description": "要存储的内容（store 时可选，提供 log_ref 时自动填充）"},
                    "log_ref": {"type": "string", "description": "日志引用，如 2026-07-22:15。提供后 Agent 自动读取内容，无需 AI 手动传 content"},
                    "source": {"type": "string", "description": "来源描述，如 read_log_line: 2026-07-22:15"}
                },
                "required": ["action"]
            }
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
    {
        "type": "function",
        "function": {
            "name": "timezone_convert",
            "description": "时区转换。把时间从一个时区转到另一个时区。不传 time_str 则用当前时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_tz": {"type": "string", "description": "目标时区，如 America/New_York"},
                    "from_tz": {"type": "string", "description": "源时区，默认 Asia/Shanghai"},
                    "time_str": {"type": "string", "description": "要转换的时间，格式 YYYY-MM-DD HH:MM，不传则用当前时间"}
                },
                "required": ["to_tz"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "timezone_list",
            "description": "列出可用时区，可选按关键词筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "筛选关键词，如 Asia、America"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_log_line",
            "description": "按 log 引用读取工具调用的完整结果。工具结果以 L2 简略格式返回时，用此工具取全文。log_ref 格式见 L2 结果中的 log:日期:行号",
            "parameters": {
                "type": "object",
                "properties": {
                    "log_ref": {"type": "string", "description": "日志引用，格式 日期:行号，如 2026-07-22:15"},
                    "start_line": {"type": "integer", "description": "可选，起始行号（从1开始）"},
                    "end_line": {"type": "integer", "description": "可选，结束行号"}
                },
                "required": ["log_ref"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "在目录中搜索匹配 pattern 的文本内容（grep 包装）",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索关键词或正则"},
                    "path": {"type": "string", "description": "搜索目录，默认当前目录"},
                    "glob": {"type": "string", "description": "文件类型过滤，如 *.py"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录下的文件和子目录，可选 glob 模式过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录"},
                    "pattern": {"type": "string", "description": "glob 过滤模式，如 *.py、**/*.md"}
                }
            }
        }
    },
]

TOOL_HANDLERS = {
    "read_file": read_file,
    "run_bash": run_bash,
    "write_file": write_file,
    "search_web": search_web,
    "timezone_convert": timezone_convert,
    "timezone_list": timezone_list,
    "read_log_line": read_log_line,
    "edit_file": edit_file,
    "search_files": search_files,
    "list_files": list_files,
}

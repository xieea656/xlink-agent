from config import get_config
import os ,readline ,json
from openai import OpenAI 
from agent import Agent 
from persona import load_persona, list_personas
from config import switch_provider , list_providers ,  switch_model , list_available_models ,ensure_credentials
import tools
from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich.markdown import Markdown
console = Console()
persona = load_persona("default")
config = get_config()
client = OpenAI(api_key=config["API_KEY"], base_url=config["Base_URL"])
def print_separator():
    console.print(Rule(style="dim"))

COMMAND_DESCRIPTIONS = {
        "exit":    "退出程序",
        "persona": "人格管理 (list/switch/current)",
        "debug":   "调试工具 (context)",
        "help":    "显示此帮助",
        "status":  "显示当前会话状态",
        "model":   "切换模型 (list/<name>)",
        "clear":   "清除历史消息，开始新会话",
        "resume":  "恢复历史会话 (不带参数列出可恢复的会话)",
        "tools" :  "列出可用工具",
        "provider" : "切换提供商 (list/<name>)",
        "notools": "切换工具开关 (on/off)",
        "plan" : "开启计划模式",
}
def handle_command(cmd):
    """解析命令并执行相应操作"""
    parts = cmd.split()
    action = parts[0][1:]  
    command_handlers = {
        "exit":  lambda: "exit",
        "persona":  lambda:handle_persona_command(parts),
        "debug":  lambda:handle_debug_command(parts),
        "help":  lambda:handle_help_command(), 
        "status": lambda:handle_status_command(),
        "model": lambda:handle_model_command(parts),
        "clear": lambda:handle_clear_command(),
        "resume": lambda:handle_resume_command(parts),
        "tools": lambda:handle_tools_command(),
        "provider":lambda:handle_provider_command(parts),
        "notools": lambda: handle_notools_command(parts),
        "plan" : lambda:handle_plan_command(), 
    }
    if action in command_handlers:
        return command_handlers[action]()
    return None

def handle_persona_command(parts):
    if len(parts) == 1:
        console.print("使用list列出人格列表，使用switch <name>切换人格，使用current查看当前人格信息")
    elif parts[1] == "list":
            personas = list_personas()
            console.print("可用的人格列表:")
            for p in personas:
                console.print(f"- {p}")
    elif parts[1] == "switch":
        if len(parts) < 3:
            console.print("请指定要切换的人格名称")
            return
        new_persona_name = parts[2]
        try:
            global persona
            persona = load_persona(new_persona_name)
            agent.persona = persona
            console.print(f"已切换到人格: {new_persona_name}")
        except FileNotFoundError as e:
            console.print(e)
    elif parts[1] == "current":
            console.print(f"当前人格: {persona['name']}")
            console.print(f"描述: {persona['description']}")
def handle_debug_command(parts):
    action = parts[1] if len(parts) > 1 else None
    if action == None:
        if len(parts) == 1:
            console.print("使用context查看上次LLM发送")
    elif parts[1] == "context":
          if agent.last_messages is None:
              console.print("没有上次的消息记录。")
              return
          else:
            for i, msg in enumerate(agent.last_messages):
                role = msg["role"]
                preview = str(msg["content"])[:80]
                tokens = len(str(msg["content"])) // 4
                console.print(f"[{i}] {role}: {tokens}t | {preview}...")
            console.print(f"总计: {sum(len(str(m['content']))//4 for m in agent.last_messages)} tokens")
def handle_help_command():
    for cmd_name, desc in COMMAND_DESCRIPTIONS.items():
        console.print(f"  /{cmd_name}  {desc}")    
def handle_tools_command():
    console.print(tools.show_tools())
def handle_status_command():
    console.print(f"当前人格: {agent.persona['name']}")
    console.print(f"当前provider: {agent.config['provider_name']}")
    console.print(f"模型： {agent.config['Model']}")
    context_tokens = agent.estimate_tokens(agent.history)
    console.print(f"{context_tokens} / {agent._trim_budget} max tokens")
    console.print(f"历史消息: {len(agent.history)} 条")
    console.print(f"当前工作目录: {os.getcwd()}")

def handle_provider_command(parts):
    if len(parts) < 2:
        console.print("输入 /provider <provider> 来切换模型提供商，输入 /provider list 查看可用提供商")
        return
    elif parts[1] == "list":
        console.print(f"当前provider: {agent.config['provider_name']}")
        console.print(f"当前模型： {agent.config['Model']}")
        providers = list_providers()
        console.print("可用的模型提供商:")
        for name, info in providers.items():
            console.print(f"- {name}: {info['default_model']}")
    else:
        provider = parts[1]
        try:
            new_config = switch_provider(provider)
        except KeyError:
            console.print(f"提供商 {provider} 不存在，请输入/provider list 查看可用提供商")
            return
        except ValueError as e:
            console.print(e)
            return
        agent.client = OpenAI(api_key=new_config["API_KEY"], base_url=new_config["Base_URL"])
        agent.config = new_config
        console.print(f"已切换到模型: {new_config['Model']} (提供者: {new_config['provider_name']})")

def handle_clear_command():
    agent.new_session()
    console.print("已清除历史消息，开始新会话。")
    
def handle_resume_command(parts):
    if len(parts) < 2:
        for fname in os.listdir("sessions"):
            if fname.endswith(".jsonl"):
                summary = first_user_msg(f"sessions/{fname}")
                console.print(f"- {fname[:-6]} | {summary}")
        return
    session_name = parts[1]
    try:
        agent.load_session(session_name)
        console.print(f"已恢复会话: {session_name} ({len(agent.history)} 条消息)")
    except FileNotFoundError:
        console.print(f"会话文件 sessions/{session_name}.jsonl 不存在。")
def first_user_msg(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = json.loads(line)
                if m.get("role") == "user":
                    return (m.get("content") or "")[:30]
    except Exception:
        pass
    return ""
def handle_model_command(parts) :
    if len(parts) < 2 or parts[1] == "list":
        ids = list_available_models(agent.client)
        if ids is None:
            console.print(" 该 provider 不支持 /model,请直接 /model <name>")
            return
        for m in ids:
            console.print(f"- {m}")
        return
    name = parts[1]
    agent.config = switch_model(name, agent.config)
    console.print(f"已切换模型: {name} (provider: {agent.config['provider_name']})")
def handle_notools_command(parts):
    if len(parts) < 2 or parts[1] == "status":
        console.print(f"工具调用: {'开启' if agent.tools_enabled else '关闭'}  (/notools on|off)")
        return
    agent.tools_enabled = (parts[1] == "on")
    console.print(f"工具调用已{'开启' if agent.tools_enabled else '关闭'}")
def handle_plan_command():
    agent.plan_mode = True
if __name__ == "__main__":
    ensure_credentials()
    agent = Agent(client, config, persona)
    while True:
        try:
            used = agent.estimate_tokens(agent.history)
            console.print(Panel(
                f"[bold cyan]{agent.config.get(chr(77)+chr(111)+chr(100)+chr(101)+chr(108), chr(63))}[/] [dim]|[/] "
                f"[bold green]{agent.config.get(chr(112)+chr(114)+chr(111)+chr(118)+chr(105)+chr(100)+chr(101)+chr(114)+chr(95)+chr(110)+chr(97)+chr(109)+chr(101), chr(63))}[/] [dim]|[/] "
                f"[bold]{used}/{agent._trim_budget} tokens[/] [dim]|[/] "
                f"[bold yellow]{agent.persona.get(chr(110)+chr(97)+chr(109)+chr(101), chr(63))}[/] [dim]|[/] "
                f"tools: [{"bold green" if agent.tools_enabled else "bold red"}]{chr(79)+chr(78) if agent.tools_enabled else chr(79)+chr(70)+chr(70)}[/]",
                style="dim"))
            console.print(Rule(style="dim"))
            cin = input("> ")
            if cin.startswith("/"):
                result = handle_command(cin)
                if result == "exit":
                    break
                continue
            if agent.plan_mode:
                if cin.lower() in ("yes", "y"):
                    agent.plan_mode=False
                    agent.tools_enabled = True
                elif cin.lower() in ("no", "n") or not cin.strip():
                    agent.plan_mode = True 
                    console.print("可继续输入新问题:")
                    continue
                else:
                    agent.plan_mode = True
            reply = agent.chat(cin)
            if reply:
                console.print()
                console.print(Markdown(reply))
            if agent.plan_mode:                         
                console.print("\n是否接受这个方案？(yes / no / 修改建议)")
        except KeyboardInterrupt:
            console.print("\n已中断任务，输入 /exit 退出程序")
        except EOFError:
            break

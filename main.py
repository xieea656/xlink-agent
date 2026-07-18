from config import get_config
import shutil , os
from openai import OpenAI 
from agent import Agent , MAX_TOKENS
from persona import load_persona, list_personas
from config import switch_provider , list_providers ,  switch_model , list_available_models
import tools
persona = load_persona("default")  #以后可以外挂到env
config = get_config()
client = OpenAI(api_key=config["API_KEY"], base_url=config["Base_URL"])
def print_separator():
    width = shutil.get_terminal_size().columns
    print("─" * width)

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
    }
    if action in command_handlers:
        return command_handlers[action]()
    return None

def handle_persona_command(parts):
    if len(parts) == 1:
        print("使用list列出人格列表，使用switch <name>切换人格，使用current查看当前人格信息")
    elif parts[1] == "list":
            personas = list_personas()
            print("可用的人格列表:")
            for p in personas:
                print(f"- {p}")
    elif parts[1] == "switch":
        if len(parts) < 3:
            print("请指定要切换的人格名称")
            return
        new_persona_name = parts[2]
        try:
            global persona
            persona = load_persona(new_persona_name)
            agent.persona = persona
            print(f"已切换到人格: {new_persona_name}")
        except FileNotFoundError as e:
            print(e)
    elif parts[1] == "current":
            print(f"当前人格: {persona['name']}")
            print(f"描述: {persona['description']}")
def handle_debug_command(parts):
    action = parts[1] if len(parts) > 1 else None
    if action == None:
        if len(parts) == 1:
            print("使用context查看上次LLM发送")
    elif parts[1] == "context":
          if agent.last_messages is None:
              print("没有上次的消息记录。")
              return
          else:
            for i, msg in enumerate(agent.last_messages):
                role = msg["role"]
                preview = str(msg["content"])[:80]
                tokens = len(str(msg["content"])) // 4
                print(f"[{i}] {role}: {tokens}t | {preview}...")
            print(f"总计: {sum(len(str(m['content']))//4 for m in agent.last_messages)} tokens")
def handle_help_command():
    for cmd_name, desc in COMMAND_DESCRIPTIONS.items():
        print(f"  /{cmd_name}  {desc}")    
def handle_tools_command():
    print(tools.show_tools())
def handle_status_command():
    print(f"当前人格: {agent.persona['name']}")
    print(f"当前provider: {agent.config['provider_name']}")
    print(f"模型： {agent.config['Model']}")
    context_tokens = sum(len(str(m.get("content", ""))) // 4 for m in agent.history)
    print(f"{context_tokens} / {MAX_TOKENS} max tokens")
    print(f"历史消息: {len(agent.history)} 条")
    print(f"当前工作目录: {os.getcwd()}")

def handle_provider_command(parts):
    if len(parts) < 2:
        print("输入 /provider <provider> 来切换模型提供商，输入 /provider list 查看可用提供商")
        return
    elif parts[1] == "list":
        print(f"当前provider: {agent.config['provider_name']}")
        print(f"当前模型： {agent.config['Model']}")
        providers = list_providers()
        print("可用的模型提供商:")
        for name, info in providers.items():
            print(f"- {name}: {info['default_model']}")
    else:
        provider = parts[1]
        try:
            new_config = switch_provider(provider)
        except KeyError:
            print(f"提供商 {provider} 不存在，请输入/provider list 查看可用提供商")
            return
        except ValueError as e:
            print(e)
            return
        agent.client = OpenAI(api_key=new_config["API_KEY"], base_url=new_config["Base_URL"])
        agent.config = new_config
        print(f"已切换到模型: {new_config['Model']} (提供者: {new_config['provider_name']})")

def handle_clear_command():
    agent.new_session()
    print("已清除历史消息，开始新会话。")
    
def handle_resume_command(parts):
    if len(parts) < 2:
        for fname in os.listdir("sessions"):
            if fname.endswith(".jsonl"):
                print(f"- {fname[:-6]}")
        return
    session_name = parts[1]
    try:
        agent.load_session(session_name)
        print(f"已恢复会话: {session_name} ({len(agent.history)} 条消息)")
    except FileNotFoundError:
        print(f"会话文件 sessions/{session_name}.jsonl 不存在。")

def handle_model_command(parts) :
    if len(parts) < 2 or parts[1] == "list":
        ids = list_available_models(agent.client)
        if ids is None:
            print(" 该 provider 不支持 /model,请直接 /model <name>")
            return
        for m in ids:
            print(f"- {m}")
        return
    name = parts[1]
    agent.config = switch_model(name, agent.config)
    print(f"已切换模型: {name} (provider: {agent.config['provider_name']})")
def handle_notools_command(parts):
    if len(parts) < 2 or parts[1] == "status":
        print(f"工具调用: {'开启' if agent.tools_enabled else '关闭'}  (/notools on|off)")
        return
    agent.tools_enabled = (parts[1] == "on")
    print(f"工具调用已{'开启' if agent.tools_enabled else '关闭'}")
        
    
if __name__ == "__main__":
    agent = Agent(client, config, persona)
    while True:
        try:
            print_separator()
            cin = input("> ")
            if cin.startswith("/"):
                result = handle_command(cin)   
                if result == "exit":
                    break
                continue
            agent.chat(cin)
        except KeyboardInterrupt:
            print("\n已中断任务，输入 /exit 退出程序")

            

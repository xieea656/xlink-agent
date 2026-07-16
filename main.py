from config import get_config
import shutil
from openai import OpenAI
from agent import Agent
from persona import load_persona, list_personas
persona = load_persona("default")  #以后可以外挂到env
config = get_config()
client = OpenAI(api_key=config["API_KEY"], base_url=config["Base_URL"])
def print_separator():
    width = shutil.get_terminal_size().columns
    print("─" * width)
def handle_command(cmd):
    """解析命令并执行相应操作"""
    parts = cmd.split()
    action = parts[0][1:]  # 去掉前面的斜杠
    if action == "exit":
        return "exit"
    elif action == "persona":
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
    elif action == "debug":
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
if __name__ == "__main__":
    agent = Agent(client, config, persona)
    while True:
        try:
            print_separator()
            cin = input("> ")
            if cin.startswith("/"):
                result = handle_command(cin)   # 命令单独处理
                if result == "exit":
                    break
                continue
            agent.chat(cin)
        except KeyboardInterrupt:
            print("\n已中断任务，输入 /exit 退出程序")
            

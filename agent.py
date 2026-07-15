from config import get_config
from openai import OpenAI
MOCK = True
class Agent:
    def __init__(self, client, config):
        self.client = client
        self.config = config
    def chat(self, cin):
        if MOCK:
            # 模拟流式输出：把一个字符串拆成字符，一个一个打印
            mock_text = "你好！这是一个模拟回复。"
            for char in mock_text:
                print(char, end="", flush=True)
            print()
            return
        response = self.client.chat.completions.create(
          model=self.config["Model"],
          messages=[{"role": "user", "content": cin}],
          stream=True,
        )
        for chunk in response:
          delta = chunk.choices[0].delta
          if delta.content:
              print(delta.content, end="", flush=True)
        print()
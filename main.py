from config import get_config
from openai import OpenAI
MOCK = True
config = get_config()
client = OpenAI(api_key=config["API_KEY"], base_url=config["Base_URL"])
def get_cin():
    cin  = input(">")
    return cin
def get_response(cin):
    if MOCK:
          # 模拟流式输出：把一个字符串拆成字符，一个一个打印
          mock_text = "你好！这是一个模拟回复。"
          for char in mock_text:
              print(char, end="", flush=True)
          print()
          return
    response = client.chat.completions.create(
      model=config["Model"],
      messages=[{"role": "user", "content": cin}],
      stream=True,
    )
    for chunk in response:
      delta = chunk.choices[0].delta
      if delta.content:
          print(delta.content, end="", flush=True)
    print()
if __name__ == "__main__":
    while True:
        cin = get_cin()
        if cin.lower() == "exit":
            break
        get_response(cin)
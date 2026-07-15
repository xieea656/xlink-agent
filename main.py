from config import get_config
from openai import OpenAI
from agent import Agent
config = get_config()
client = OpenAI(api_key=config["API_KEY"], base_url=config["Base_URL"])
if __name__ == "__main__":
    agent = Agent(client, config)
    while True:
        cin = input(">")
        if cin.lower() == "exit":
            break
        agent.chat(cin)

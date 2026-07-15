import os 
from dotenv import load_dotenv

load_dotenv()
def get_config():
    if not os.path.exists(".env"):
        raise FileNotFoundError("请重命名 .env.example 为 .env 并填入 API Key")
    else:
        API_KEY = os.getenv("API_KEY")
        Base_URL = os.getenv("Base_URL")
        Model = os.getenv("Model")
        if not API_KEY or not Base_URL or not Model:
            raise ValueError("请在 .env 文件中填写 API Key、Base URL 和 Model")
        return{"API_KEY": API_KEY, "Base_URL": Base_URL, "Model": Model}

if __name__ == "__main__":
    config = get_config()
    print(config)

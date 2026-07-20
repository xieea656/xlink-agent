import os ,yaml
from dotenv import load_dotenv
from rich.console import Console
_NON_CHAT = ("asr", "tts", "voice", "embedding", "whisper")
load_dotenv()
console = Console()
with open("config.yaml", "r", encoding="utf-8") as f:
     yaml_config = yaml.safe_load(f)
default = yaml_config["default_provider"]          
provider = yaml_config["providers"][default] 
API_KEY = os.getenv(provider["api_key_env"])       
if not API_KEY:
      raise ValueError(f"请在 .env 中设置 {provider['api_key_env']}")
Base_URL = provider["base_url"]
Model    = provider["default_model"]

def get_config():
    return{"API_KEY": API_KEY, "Base_URL": Base_URL, "Model": Model,"provider_name": default,}
def list_providers():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["providers"]
def switch_provider(name):
    with open("config.yaml", "r", encoding="utf-8") as f:
        providers = yaml.safe_load(f)["providers"]
    if name not in providers:
          raise KeyError(name)
    info = providers[name]
    api_key = os.getenv(info["api_key_env"])
    if not api_key:
        raise ValueError(f"请在 .env 中设置 {info['api_key_env']}")
    return {
          "API_KEY": api_key,
          "Base_URL": info["base_url"],
          "Model": info["default_model"],
          "provider_name": name,
      }
def switch_model(model_name, current_config):
    new = dict(current_config)
    new["Model"] = model_name
    return new
def list_available_models(client):
    try:
        resp = client.models.list()
    except Exception:          
        return None
    ids = []                   
    for m in resp.data:        
        low = m.id.lower()
        if any(x in low for x in _NON_CHAT):   
            continue
        ids.append(m.id)       
    return sorted(ids)
def resolve_credential(name):
    """从 credentials.yaml 按名查找凭证，返回 value"""
    path = os.path.expanduser("~/.config/myagent/credentials.yaml")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        creds = yaml.safe_load(f) or {}
    entry = creds.get(name)
    if not entry:
        return None
    if entry.get("type") == "env":
        return os.getenv(entry["value"])
    return entry.get("value")
def ensure_credentials():
    """检测 credentials.yaml，不存在则交互式初始化"""
    path = os.path.expanduser("~/.config/myagent/credentials.yaml")
    if os.path.exists(path):
          return
    console.print("检测到首次运行，请配置凭证（留空=跳过/匿名）")
    anysearch_key = input("AnySearch API key (回车匿名): ").strip()
    data = {}
    if anysearch_key:
        data["anysearch"] = {"type": "api-key", "value": anysearch_key}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)
    os.chmod(path, 0o600)
    console.print(f"凭证已保存到: {path}")
            
if __name__ == "__main__":
    config = get_config()
    console.print(config)

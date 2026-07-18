from config import get_config
from openai import OpenAI
from system_prompt import SYSTEM_PROMPT
import datetime, os, platform , json
from tools import TOOL_SPECS, call_tool_dict
MOCK = False
MAX_TOKENS = 8000
MAX_ITER = 25
class Agent:
    def __init__(self, client, config,persona):
        self.client = client
        self.config = config
        self.persona = persona
        self.history = []
        self.last_messages = None
        self._new_session_file()
        self.tools_enabled = True
    def chat(self, cin):
        
        if MOCK:
            mock_text = "你好！这是一个模拟回复。"
            for char in mock_text:
                print(char, end="", flush=True)
            print()
            self.last_messages = [                   
                {"role": "system", "content": self.persona["system_prompt"]},
                {"role": "user", "content": cin},
                {"role": "assistant", "content": mock_text}
            ]
            return
        user_msg = {"role": "user", "content": cin}
        self.history.append(user_msg)
        self._append_jsonl(user_msg)
        last_content = ""
        for step in range(MAX_ITER):
            messages = self._build_messages()
            self._trim_to_budget(messages)
            self.last_messages = messages
            used = self.estimate_tokens(messages)
            r = self._stream_completion(messages, self._active_tools())
            print(f"[step {step+1} | {used} tokens]")
            last_content = r["content"]
            asst = {"role": "assistant", "content": r["content"] or None}
            if r["tool_calls"]:
                asst["tool_calls"] = r["tool_calls"]
            self.history.append(asst)
            self._append_jsonl(asst)
            if not r["tool_calls"]:
                return last_content
            for call in r["tool_calls"]:
                result = call_tool_dict(call)
                tool_msg = {"role":"tool", "tool_call_id": call["id"],"content": result}
                self.history.append(tool_msg)
                self._append_jsonl(tool_msg)
        print(f"\n[!] 达到最大迭代次数 {MAX_ITER},回答可能不完整。")
        return last_content

    def estimate_tokens(self, messages):
        """粗略估算 token 数：总字符数 / 4"""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return (total_chars + 3) // 4
    def get_env_info(self):
        """获取环境信息"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z")
        cwd = os.getcwd()
        os_name = f"{platform.system()} {platform.release()}"
        return f"当前时间: {now}\n工作目录: {cwd}\n操作系统: {os_name}"
    def new_session(self):
        """开始新会话"""
        self._new_session_file()
        self.history = []

    def _new_session_file(self):
        os.makedirs("sessions", exist_ok=True)
        self.session_file = "sessions/" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl"

    def load_session(self,name):
        if name.endswith(".jsonl"):
            name = name[:-6]
        path = f"sessions/{name}.jsonl"
        with open(path, "r", encoding="utf-8") as f:
            self.history = [json.loads(line) for line in f if line.strip()]
            self.session_file = path
    def _stream_completion(self,messages,tools=None):
        """构造 assistant 消息"""
        kwargs = dict(model = self.config["Model"],messages=messages,stream=True)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self.client.chat.completions.create(**kwargs)
        content = ""
        tc_acc = {}
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "reasoning_content", None):
                print(delta.reasoning_content, end="", flush=True)
            if delta.content:
                print(delta.content, end="", flush=True)
                content += delta.content
            for tc in (getattr(delta, "tool_calls", None) or []):
                slot = tc_acc.setdefault(tc.index, {"id":"", "name":"", "arguments":""})
                if tc.id: slot["id"] = tc.id 
                if tc.function:
                    if tc.function.name: slot["name"] = tc.function.name
                    if tc.function.arguments: slot["arguments"] += tc.function.arguments
        print()
        tool_calls = None
        if tc_acc:
            tool_calls = [
                {"id": v["id"], "type": "function",
                "function": {"name": v["name"], "arguments": v["arguments"]}}
                for _, v in sorted(tc_acc.items())
            ]
        return {"content": content, "tool_calls": tool_calls}
    def _build_messages(self):
        messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": self.persona["system_prompt"]},
                *self.history,
                {"role": "system", "content": self.get_env_info()},
            ]
        return messages
    def  _append_jsonl(self, obj):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n") 
    def _active_tools(self):
        if not self.tools_enabled:
            return None
        return TOOL_SPECS
    def _atomic_units(self, history):
        units = []
        i = 0
        while i < len(history):
            j = i+1
            if history[i].get("tool_calls"):
                while j < len(history) and history[j]["role"] == "tool":
                    j +=1
                units.append((i,j))
            else :
                units.append((i,i+1))
            i = j
        return units
    def _trim_to_budget(self, messages):
        while self.estimate_tokens(messages) > MAX_TOKENS:
            units = self._atomic_units(self.history)
            if len(units) <= 1:
                break
            s,e = units[0]
            if e < len(self.history) and self.history[e]["role"] != "user":
                k = next((idx for idx in range(1, len(units)) if self.history[units[idx][0]]["role"] == "user"), None)
                if k is None:
                    break
                e = units[k][0]
            del self.history[s:e]
            messages[:] = self._build_messages()
    


                    
                


            

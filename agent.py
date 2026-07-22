from config import get_config
from openai import OpenAI
from system_prompt import SYSTEM_PROMPT ,PLAN_PROMPT ,COMPRESS_SYSTEM,COMPRESS_PROMPT
import datetime, os, platform , json ,tiktoken
from tools import TOOL_SPECS, call_tool_dict,LOW_TOOL_SPECS ,TOOL_HANDLERS
from log import log_tool_call, l2_summary, read_line
from events import EventBus
from message import AgentMessage 
_enc = tiktoken.get_encoding("cl100k_base")
MAX_ITER = 25
COMPRESS_RESERVE_ROUNDS = 4
COMPRESS_TRIGGER_RATIO = 0.8
WM_MAX_TOKENS = 3000
WM_MAX_ENTRIES = 30
TS_MAX_ENTRIES = 10
class Agent:
    def __init__(self, client, config,persona):
        self.client = client
        self.config = config
        self.persona = persona
        self.history = []
        self.last_messages = None
        self._new_session_file()
        self.tools_enabled = True
        self.plan_mode = False
        self._trim_budget = config["context_window"] * 0.8
        self.events = EventBus()
        self.compressed = []
        self.working_memory = []
        self.tool_storage = {}
        self.plan_text = None
    def chat(self, cin):
        user_msg = AgentMessage(role="user", content=cin)
        self.history.append(user_msg)
        self._append_jsonl(user_msg)
        last_content = ""
        for step in range(MAX_ITER):
            messages = self._build_messages()
            self.last_messages = messages
            used = self.estimate_tokens(messages)
            self.events.emit("step_start",step=step+1, tokens=used)
            r = self._stream_completion(messages, self._active_tools())
            last_content = r["content"]
            asst = AgentMessage(role="assistant", content=r["content"] or "", tool_calls=r["tool_calls"])
            self.history.append(asst)
            self._append_jsonl(asst)
            if not r["tool_calls"]:
                self._compress()
                self.events.emit("response_done", content=last_content)
                return last_content
            for call in r["tool_calls"]:
                if call["function"]["name"] == "enter_plan_mode":
                    self.plan_mode = True
                    continue
                if call["function"]["name"] == "remember":
                    self.events.emit("tool_call", name="remember", args=json.loads(call["function"]["arguments"]))
                    self._handle_remember(call)
                    continue
                if call["function"]["name"] == "store_tool_result":
                    self.events.emit("tool_call", name="store_tool_result", args=json.loads(call["function"]["arguments"]))
                    self._handle_store_tool_result(call)
                    continue
                self.events.emit("tool_call", name=call["function"]["name"], args=json.loads(call["function"]["arguments"]))
                result = call_tool_dict(call)
                status = "error" if result.startswith("Error:") else "success"
                self.events.emit("tool_result", name=call["function"]["name"], status=status, result=result)
                date, ln = log_tool_call(
                    name = call["function"]["name"],
                    args = json.loads(call["function"]["arguments"]),
                    result = result,
                    status= status,
                )
                l2 = l2_summary(call["function"]["name"], result, status, date, ln)
                if len(result) < 500 or call["function"]["name"] == "read_log_line":
                    tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
                else:
                    tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=l2)
                self.history.append(tool_msg)
                self._append_jsonl(tool_msg)
        self.events.emit("max_iter", max_iter=25)
        return last_content
    def estimate_tokens(self, messages):
        """计算token数"""
        total = 0
        for m in messages:
            content = m.content if hasattr(m, "content") else m.get("content", "")
            total += len(_enc.encode(content))
            total += 4   
        return total
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
        self.working_memory = []
        self.tool_storage = {}
        self.plan_text = None
        self.compressed = []

    def _new_session_file(self):
        os.makedirs("sessions", exist_ok=True)
        self.session_file = "sessions/" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl"

    def load_session(self,name):
        if name.endswith(".jsonl"):
            name = name[:-6]
        path = f"sessions/{name}.jsonl"
        with open(path, "r", encoding="utf-8") as f:
            self.history = [AgentMessage.from_dict(json.loads(line)) for line in f if line.strip()]
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
                self.events.emit("reasoning_delta", text=delta.reasoning_content)
            if delta.content:
                self.events.emit("text_delta", text=delta.content)
                content += delta.content
            for tc in (getattr(delta, "tool_calls", None) or []):
                slot = tc_acc.setdefault(tc.index, {"id":"", "name":"", "arguments":""})
                if tc.id: slot["id"] = tc.id 
                if tc.function:
                    if tc.function.name: slot["name"] = tc.function.name
                    if tc.function.arguments: slot["arguments"] += tc.function.arguments
        tool_calls = None
        if tc_acc:
            tool_calls = [
                {"id": v["id"], "type": "function",
                "function": {"name": v["name"], "arguments": v["arguments"]}}
                for _, v in sorted(tc_acc.items())
            ]
        return {"content": content, "tool_calls": tool_calls}
    def _build_messages(self):
        messages = []
        # ① 系统提示词
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
        # ② 人格提示词
        messages.append({"role": "system", "content": self.persona["system_prompt"]})
        # ③ 计划（静态，AI 确认后提取，不可修改）
        if self.plan_text:
            messages.append({"role": "system", "content": f"## 当前计划\n{self.plan_text}"})
        elif self.plan_mode:
            messages.append({"role": "system", "content": PLAN_PROMPT})
        # ④ 压缩的上下文
        for m in self.compressed:
            messages.append({"role": "system", "content": m.content})
        # ⑤ + ⑥ 历史分区
        history = [m.to_llm() for m in self.history]
        # 找到最后一条用户消息的位置
        last_user_idx = -1
        for i in range(len(history) - 1, -1, -1):
            if history[i]["role"] == "user":
                last_user_idx = i
                break
        if last_user_idx >= 0:
            # ⑤ 被保留的未压缩上下文（最后一条用户消息之前的所有历史）
            messages.extend(history[:last_user_idx])
            # ⑥ 这一轮新增的内容（最后一条用户消息 + 后续工具结果）
            messages.extend(history[last_user_idx:])
        else:
            messages.extend(history)
        # ⑦ 工作记忆
        wm_text = self._working_memory_text()
        if wm_text:
            messages.append({"role": "system", "content": f"## 工作记忆\n{wm_text}"})
        # ⑧ 额外的工具存储
        ts_text = self._tool_storage_text()
        if ts_text:
            messages.append({"role": "system", "content": f"## 工具存储\n{ts_text}"})
        # ⑨ 环境注入
        messages.append({"role": "system", "content": self.get_env_info()})
        # ⑩ 用户消息重放（最后一条，recency 效应最大）
        if last_user_idx >= 0:
            user_msg = history[last_user_idx]
            messages.append({"role": "system", "content": f"## 用户消息重放（非新请求，仅作参考）\n{user_msg['content']}"})
        return messages
    def  _append_jsonl(self, msg):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n") 
    def _active_tools(self):
        if not self.tools_enabled:
            return None                  
        if self.plan_mode:
            return LOW_TOOL_SPECS 
        return TOOL_SPECS       
    def _atomic_units(self, history):
        units = []
        i = 0
        while i < len(history):
            j = i+1
            if history[i].tool_calls:
                while j < len(history) and history[j].role == "tool":
                    j +=1
                units.append((i,j))
            else :
                units.append((i,i+1))
            i = j
        return units
    def _assemble_compress_content(self, units):
        parts = []
        for m in self.compressed:
            parts.append(f"[压缩摘要]\n{m.content}")
        for s, e in units:
            for msg in self.history[s:e]:
                parts.append(f"[{msg.role}]\n{msg.content}")
        return "\n\n".join(parts)
    def _compress(self):
        total = self.estimate_tokens(self.history) + self.estimate_tokens(self.compressed)
        if total < COMPRESS_TRIGGER_RATIO * self._trim_budget:
            return
        units = self._atomic_units(self.history)
        if len(units) <= COMPRESS_RESERVE_ROUNDS + 1:
            return
        to_compress = self._assemble_compress_content(units[:-COMPRESS_RESERVE_ROUNDS])
        target = max(5000, len(_enc.encode(to_compress)) // 5)
        summary = self._compress_request(to_compress, target)
        self.compressed.append(AgentMessage(role="compressed", content=summary))
        cut = units[-COMPRESS_RESERVE_ROUNDS][0]
        self.history = self.history[cut:]
    def _compress_request(self, content, target):
        resp = self.client.chat.completions.create(
          model=self.config["Model"],
          messages=[
                {"role": "system", "content": COMPRESS_SYSTEM},
                {"role": "user", "content": COMPRESS_PROMPT.format(content=content, target=target)}
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content
    def _handle_remember(self, call):
        args = json.loads(call["function"]["arguments"])
        action = args.get("action", "add")
        fact = args.get("fact", "")
        importance = args.get("importance", "medium")
        if action == "add":
            self.working_memory.append({
                "fact": fact, "importance": importance,
                "time": datetime.datetime.now().strftime("%m-%d %H:%M")
            })
            self._trim_working_memory()
            content = "✓"
        elif action == "remove":
            n = sum(1 for m in self.working_memory if m["fact"] == fact)
            self.working_memory = [m for m in self.working_memory if m["fact"] != fact]
            content = f"已删除 {n} 条"
        elif action == "list":
            if not self.working_memory:
                content = "(空)"
            else:
                lines = [f"[{i}] {m['time']} [{m['importance']}] {m['fact']}" for i, m in enumerate(self.working_memory)]
                content = "\n".join(lines)
        elif action == "clear":
            n = len(self.working_memory)
            self.working_memory = []
            content = f"已清空 {n} 条"
        else:
            content = f"Error: 未知操作 {action}"
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=content)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="remember", status="success", result=content)
    def _handle_store_tool_result(self, call):
        args = json.loads(call["function"]["arguments"])
        action = args.get("action", "store")
        key = args.get("key", "")
        content_arg = args.get("content", "")
        source = args.get("source", "")
        log_ref = args.get("log_ref", "")
        if action == "store":
            if not key:
                content = "Error: key is required"
            elif not content_arg and not log_ref:
                content = "Error: 需要提供 content 或 log_ref"
            else:
                if log_ref and not content_arg:
                    try:
                        parts = log_ref.replace("log:", "").split(":")
                        date, line_num = parts[0], parts[1]
                        entry = read_line(date, int(line_num))
                        if entry:
                            content_arg = json.dumps(entry, ensure_ascii=False, indent=2)
                            if not source:
                                source = f"read_log_line: {log_ref}"
                        else:
                            content = f"Error: 未找到日志 {log_ref}"
                            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=content)
                            self.history.append(tool_msg)
                            self._append_jsonl(tool_msg)
                            self.events.emit("tool_result", name="store_tool_result", status="error", result=content)
                            return
                    except Exception as e:
                        content = f"Error: 读取日志失败: {e}"
                        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=content)
                        self.history.append(tool_msg)
                        self._append_jsonl(tool_msg)
                        self.events.emit("tool_result", name="store_tool_result", status="error", result=content)
                        return
                self.tool_storage[key] = {
                    "content": content_arg, "source": source,
                    "time": datetime.datetime.now().strftime("%m-%d %H:%M")
                }
                if len(self.tool_storage) > TS_MAX_ENTRIES:
                    oldest = min(self.tool_storage, key=lambda k: self.tool_storage[k]["time"])
                    del self.tool_storage[oldest]
                content = f"已存储: {key} ({len(content_arg)} 字符)"
        elif action == "remove":
            if key in self.tool_storage:
                del self.tool_storage[key]
                content = f"已删除: {key}"
            else:
                content = f"未找到: {key}"
        elif action == "list":
            if not self.tool_storage:
                content = "(空)"
            else:
                content = "\n".join(f"[{k}] [{v['time']}] {v['source']}" for k, v in self.tool_storage.items())
        elif action == "clear":
            n = len(self.tool_storage)
            self.tool_storage = {}
            content = f"已清空 {n} 项"
        else:
            content = f"Error: 未知操作 {action}"
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=content)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="store_tool_result", status="success", result=content)
    def _working_memory_text(self):
        if not self.working_memory:
            return ""
        return "\n".join(f"[{m['time']}][{m['importance']}] {m['fact']}" for m in self.working_memory)
    def _tool_storage_text(self):
        if not self.tool_storage:
            return ""
        items = []
        for k, v in self.tool_storage.items():
            items.append(f"[{v['time']}][{k}][{v['source']}]\n{v['content']}")
        return "\n\n".join(items)
    def _trim_working_memory(self):
        while len(self.working_memory) > WM_MAX_ENTRIES:
            self.working_memory.pop(0)
        wm_text = self._working_memory_text()
        if wm_text and self.estimate_tokens([{"content": wm_text}]) > WM_MAX_TOKENS:
            while self.working_memory and self.estimate_tokens([{"content": self._working_memory_text()}]) > WM_MAX_TOKENS:
                self.working_memory.pop(0)
                

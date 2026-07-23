from config import get_config
from openai import OpenAI
from system_prompt import SYSTEM_PROMPT ,PLAN_PROMPT ,COMPRESS_SYSTEM,COMPRESS_PROMPT
import datetime, os, platform , json ,tiktoken
from tools import TOOL_SPECS, call_tool_dict,LOW_TOOL_SPECS ,TOOL_HANDLERS
from log import log_tool_call, l2_summary, read_line
from events import EventBus
from message import AgentMessage
from memory_index import MemoryIndex 
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
        self.protected_ids = set()
        self.memory_index = MemoryIndex()
        self.memory_index_text = ""
        self.memory_dir = ".xlink/memory/"
        self.max_iter = MAX_ITER
        self.compress_reserve_rounds = COMPRESS_RESERVE_ROUNDS
        self.compress_trigger_ratio = COMPRESS_TRIGGER_RATIO
        self.wm_max_tokens = WM_MAX_TOKENS
        self.wm_max_entries = WM_MAX_ENTRIES
        self.ts_max_entries = TS_MAX_ENTRIES
    def chat(self, cin):
        user_msg = AgentMessage(role="user", content=cin)
        self.history.append(user_msg)
        self._append_jsonl(user_msg)
        last_content = ""
        for step in range(self.max_iter):
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
                if call["function"]["name"] == "recall_history":
                    self.events.emit("tool_call", name="recall_history", args=json.loads(call["function"]["arguments"]))
                    self._handle_recall_history(call)
                    continue
                if call["function"]["name"] == "remember_memory":
                    self.events.emit("tool_call", name="remember_memory", args=json.loads(call["function"]["arguments"]))
                    self._handle_remember_memory(call)
                    continue
                if call["function"]["name"] == "forget_memory":
                    self.events.emit("tool_call", name="forget_memory", args=json.loads(call["function"]["arguments"]))
                    self._handle_forget_memory(call)
                    continue
                if call["function"]["name"] == "read_memory":
                    self.events.emit("tool_call", name="read_memory", args=json.loads(call["function"]["arguments"]))
                    self._handle_read_memory(call)
                    continue
                if call["function"]["name"] == "search_memories":
                    self.events.emit("tool_call", name="search_memories", args=json.loads(call["function"]["arguments"]))
                    self._handle_search_memories(call)
                    continue
                if call["function"]["name"] == "list_memories":
                    self.events.emit("tool_call", name="list_memories", args=json.loads(call["function"]["arguments"]))
                    self._handle_list_memories(call)
                    continue
                self.events.emit("tool_call", name=call["function"]["name"], args=json.loads(call["function"]["arguments"]))
                result = call_tool_dict(call)
                status = "error" if result.startswith("Error:") else "success"
                self.events.emit("tool_result", name=call["function"]["name"], status=status, result=result)
                if status == "error":
                    err_msg = result[:200]
                    name = call["function"]["name"]
                    self._handle_remember_auto(f"工具 {name} 失败: {err_msg}")
                date, ln = log_tool_call(
                    name = call["function"]["name"],
                    args = json.loads(call["function"]["arguments"]),
                    result = result,
                    status= status,
                )
                l2 = l2_summary(call["function"]["name"], result, status, date, ln)
                MEMORY_TOOLS = {"remember_memory", "forget_memory", "read_memory", "search_memories", "list_memories"}
                if len(result) < 500 or call["function"]["name"] in MEMORY_TOOLS | {"read_log_line"}:
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
        self._new_session_file()
        self.memory_index.set_session(self.session_file)
        self.history = []
        self.working_memory = []
        self.tool_storage = {}
        self.plan_text = None
        self.protected_ids = set()
        self.compressed = []
        self.memory_index_text = self._load_memory_index()

    def _new_session_file(self):
        os.makedirs(".xlink/sessions", exist_ok=True)
        self.session_file = ".xlink/sessions/" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl"

    def load_session(self,name):
        if name.endswith(".jsonl"):
            name = name[:-6]
        path = f".xlink/sessions/{name}.jsonl"
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
        # ⑨-b 持久记忆索引（跨会话，不会随压缩丢弃）
        if self.memory_index_text:
            messages.append({"role": "system", "content": f"## 持久记忆\n{self.memory_index_text}"})
        # ⑩ 用户消息重放（最后一条，recency 效应最大）
        if last_user_idx >= 0:
            user_msg = history[last_user_idx]
            messages.append({"role": "system", "content": f"## 用户消息重放（非新请求，仅作参考）\n{user_msg['content']}"})
        return messages
    def  _append_jsonl(self, msg):
        self.memory_index.index_message(msg)
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
        if total < self.compress_trigger_ratio * self._trim_budget:
            return
        units = self._atomic_units(self.history)
        if len(units) <= self.compress_reserve_rounds + 1:
            return
        to_compress = self._assemble_compress_content(units[:-self.compress_reserve_rounds])
        target = max(5000, len(_enc.encode(to_compress)) // 5)
        episode, memories, user_msgs = self._compress_request(to_compress, target)
        # ① episode → ④ 压缩上下文
        self.compressed.append(AgentMessage(role="compressed", content=episode))
        # ② memory → .xlink/memory/
        if memories:
            for item in memories:
                self._write_compressed_memory(item)
            self._sync_memory_index()
        # ③ user → .xlink/compressed/users/
        if user_msgs:
            self._save_compressed_users(user_msgs)
        cut = units[-self.compress_reserve_rounds][0]
        keep = [m for m in self.history[:cut] if m.id in self.protected_ids]
        self.history = keep + self.history[cut:]
    def _compress_request(self, content, target):
        resp = self.client.chat.completions.create(
          model=self.config["Model"],
          messages=[
                {"role": "system", "content": COMPRESS_SYSTEM},
                {"role": "user", "content": COMPRESS_PROMPT.format(content=content, target=target)}
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return self._parse_compressed_response(raw)
    def _parse_compressed_response(self, raw):
        episode = ""
        memory_items = []
        user_messages = ""
        current = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped == "=== EPISODE ===":
                current = "episode"
            elif stripped == "=== MEMORY ===":
                current = "memory"
            elif stripped == "=== USER_MESSAGES ===":
                current = "user"
            elif current == "episode":
                episode += line + "\n"
            elif current == "memory":
                if stripped.startswith("- [name:"):
                    memory_items.append(stripped)
            elif current == "user":
                user_messages += line + "\n"
        # 容错：没找到标记时整段当 episode
        if not episode and not memory_items and not user_messages:
            episode = raw
        return episode.strip(), memory_items, user_messages.strip()

    def _parse_memory_item(self, line):
        name = ""
        content = ""
        type_ = "reference"
        desc = ""
        # 格式: - [name: 记忆名] 内容 | type: 类型 | desc: 描述
        line = line.lstrip("- ")
        if line.startswith("[name:"):
            end = line.find("]")
            if end > 0:
                name = line[6:end].strip()
                rest = line[end+1:].strip()
                parts = rest.split(" | ")
                if parts:
                    content = parts[0]
                for p in parts[1:]:
                    if p.startswith("type:"):
                        type_ = p[5:].strip()
                    elif p.startswith("desc:"):
                        desc = p[5:].strip()
        return name, content, type_, desc

    def _write_compressed_memory(self, item):
        name, content, type_, desc = self._parse_memory_item(item)
        if not name or not content:
            return
        fpath = os.path.join(self.memory_dir, f"{name}.md")
        frontmatter = f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: {type_}\n  source: compressed\n---\n\n"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(frontmatter + content)

    def _save_compressed_users(self, text):
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.datetime.now().strftime("%H:%M")
        save_dir = os.path.join(".xlink", "compressed", "users")
        os.makedirs(save_dir, exist_ok=True)
        fpath = os.path.join(save_dir, f"{date}.md")
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(f"\n## {time_str}\n\n{text}\n")

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
                if len(self.tool_storage) > self.ts_max_entries:
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

    def _handle_recall_history(self, call):
        args = json.loads(call["function"]["arguments"])
        query = args.get("query", "")
        limit = args.get("limit", 5)
        days = args.get("days", 30)
        results = self.memory_index.search(query, limit, days)
        if not results:
            content = "未找到匹配的历史"
        else:
            lines = [f"[{s[1][:8]}...] [{s[3]}] {s[4]}" for s in results]
            content = f"找到 {len(results)} 条匹配:\n" + "\n---\n".join(lines)
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=content)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="recall_history", status="success", result=content)

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
        while len(self.working_memory) > self.wm_max_entries:
            self.working_memory.pop(0)
        wm_text = self._working_memory_text()
        if wm_text and self.estimate_tokens([{"content": wm_text}]) > self.wm_max_tokens:
            while self.working_memory and self.estimate_tokens([{"content": self._working_memory_text()}]) > self.wm_max_tokens:
                self.working_memory.pop(0)

    def _handle_remember_auto(self, fact):
        """自动记入工作记忆（工具失败时调用）"""
        self.working_memory.append({
            "fact": fact, "importance": "high",
            "time": datetime.datetime.now().strftime("%m-%d %H:%M")
        })
        self._trim_working_memory()

    def _load_memory_index(self):
        path = os.path.join(self.memory_dir, "MEMORY.md")
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _sync_memory_index(self):
        os.makedirs(self.memory_dir, exist_ok=True)
        index_path = os.path.join(self.memory_dir, "MEMORY.md")
        files = sorted(f for f in os.listdir(self.memory_dir)
                       if f.endswith(".md") and f != "MEMORY.md")
        lines = []
        for fname in files:
            fpath = os.path.join(self.memory_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            name = fname[:-3]
            desc = ""
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().splitlines():
                        if line.startswith("description:"):
                            desc = line[len("description:"):].strip().strip("\"").strip("'")
                            break
            lines.append(f"- [{name}]({fname}) — {desc}" if desc else f"- [{name}]({fname})")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n" if lines else "")
        self.memory_index_text = "\n".join(lines)

    def _handle_remember_memory(self, call):
        args = json.loads(call["function"]["arguments"])
        name = args.get("name", "")
        content = args.get("content", "")
        type_ = args.get("type", "reference")
        description = args.get("description", "")
        if not name or not content:
            result = "Error: 需要提供 name 和 content"
            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
            self.history.append(tool_msg)
            self._append_jsonl(tool_msg)
            self.events.emit("tool_result", name="remember_memory", status="error", result=result)
            return
        fname = f"{name}.md"
        fpath = os.path.join(self.memory_dir, fname)
        frontmatter = f"---\nname: {name}\ndescription: {description}\nmetadata:\n  type: {type_}\n---\n\n"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(frontmatter + content)
        self._sync_memory_index()
        result = f"已记忆: {name}"
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="remember_memory", status="success", result=result)

    def _handle_forget_memory(self, call):
        args = json.loads(call["function"]["arguments"])
        name = args.get("name", "")
        if not name:
            result = "Error: 需要提供 name"
            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
            self.history.append(tool_msg)
            self._append_jsonl(tool_msg)
            self.events.emit("tool_result", name="forget_memory", status="error", result=result)
            return
        fpath = os.path.join(self.memory_dir, f"{name}.md")
        if os.path.exists(fpath):
            os.remove(fpath)
            self._sync_memory_index()
            result = f"已遗忘: {name}"
        else:
            result = f"未找到记忆: {name}"
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="forget_memory", status="success", result=result)

    def _handle_read_memory(self, call):
        args = json.loads(call["function"]["arguments"])
        name = args.get("name", "")
        if not name:
            result = "Error: 需要提供 name"
            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
            self.history.append(tool_msg)
            self._append_jsonl(tool_msg)
            self.events.emit("tool_result", name="read_memory", status="error", result=result)
            return
        fpath = os.path.join(self.memory_dir, f"{name}.md")
        if not os.path.exists(fpath):
            result = f"未找到记忆: {name}"
            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
            self.history.append(tool_msg)
            self._append_jsonl(tool_msg)
            self.events.emit("tool_result", name="read_memory", status="error", result=result)
            return
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        content = re.sub(r"\[\[([^\]]+)\]\]", r"[\1](see also: \1)", content)
        result = content
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="read_memory", status="success", result=result)

    def _handle_search_memories(self, call):
        args = json.loads(call["function"]["arguments"])
        query = args.get("query", "")
        if not query:
            result = "Error: 需要提供 query"
            tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
            self.history.append(tool_msg)
            self._append_jsonl(tool_msg)
            self.events.emit("tool_result", name="search_memories", status="error", result=result)
            return
        os.makedirs(self.memory_dir, exist_ok=True)
        matches = []
        for fname in sorted(os.listdir(self.memory_dir)):
            if not fname.endswith(".md") or fname == "MEMORY.md":
                continue
            fpath = os.path.join(self.memory_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    file_lines = f.readlines()
                for i, line in enumerate(file_lines, 1):
                    if query.lower() in line.lower():
                        matches.append(f"  {fname[:-3]}:{i} | {line.strip()[:120]}")
            except Exception:
                continue
        if not matches:
            result = f"未找到匹配 '{query}' 的记忆"
        else:
            result = f"找到 {len(matches)} 条匹配:\n" + "\n".join(matches[:30])
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="search_memories", status="success", result=result)

    def _handle_list_memories(self, call):
        os.makedirs(self.memory_dir, exist_ok=True)
        index_path = os.path.join(self.memory_dir, "MEMORY.md")
        if not os.path.exists(index_path):
            self._sync_memory_index()
        if not os.path.exists(index_path):
            result = "(空)"
        else:
            with open(index_path, "r", encoding="utf-8") as f:
                result = f.read().strip() or "(空)"
        tool_msg = AgentMessage(role="tool", tool_call_id=call["id"], content=result)
        self.history.append(tool_msg)
        self._append_jsonl(tool_msg)
        self.events.emit("tool_result", name="list_memories", status="success", result=result)


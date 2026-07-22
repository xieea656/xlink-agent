import os ,json , datetime
os.makedirs("logs", exist_ok=True)
def log_tool_call(name , args, result ,status):
    """写工具日志，返回行号"""
    path ="logs/" + datetime.datetime.now().strftime("%Y-%m-%d") + "_tools.jsonl"
    entry = {
        "timestamp" : datetime.datetime.now().strftime("%Y%m%d_%H%M%S") ,
        "tool" : name ,
        "input" : args,
        "output" : result,
        "status": status
    }
    with open(path, "a", encoding="utf-8") as f:
        line_num = sum(1 for _ in open(path, "r", encoding="utf-8")) + 1
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return line_num
def read_tool_log(name):
    """读工具日志"""
    path = f"logs/{name}_tools.jsonl"
    with open(path, "r", encoding="utf-8") as f:
        logs = [json.loads(line) for line in f if line.strip()]
    return logs
def read_line(date, line_num, start_line=None, end_line=None):
    """按行号读单条日志，可选截 output 的行范围。date='2024-07-22', line_num=3"""
    path = f"logs/{date}_tools.jsonl"
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i == line_num:
                entry = json.loads(line)
                if start_line is not None:
                    lines = entry["output"].splitlines()
                    entry["output"] = "\n".join(lines[start_line-1:end_line])
                return entry
    return None
        
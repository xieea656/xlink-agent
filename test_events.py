from events import EventBus

bus = EventBus()

# 注册两个监听
def handler1(data):
    print(f"[终端] 工具执行: {data['name']}")

def handler2(data):
    print(f"[日志] 归档: {data['name']} -> {data['result'][:20]}...")

bus.on("tool_executed", handler1)
bus.on("tool_executed", handler2)

# 模拟 agent 执行工具
print("=== emit 第一次 ===")
bus.emit("tool_executed", name="read_file", result="hello world\nline2")

# 取消一个监听
print("\n=== 取消 handler2 ===")
bus.off("tool_executed", handler2)

# 再次 emit
print("=== emit 第二次 ===")
bus.emit("tool_executed", name="run_bash", result="hi")

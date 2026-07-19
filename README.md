# myagent

一个 CLI AI Agent，支持多模型、多人格、工具调用、计划模式。

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/xieea656/myagent.git
cd myagent

# 2. 安装依赖
pip install rich openai pyyaml

# 3. 配置
cp config.yaml config.yaml  # 编辑 API 密钥
# 或创建 .env 文件写入 API_KEY 和 Base_URL

# 4. 运行
python main.py
```

## 功能

| 功能 | 说明 |
|------|------|
| 多模型切换 | `/model` 切换模型，`/provider` 切换提供商 |
| 人格系统 | `/persona` 切换人格，YAML 文件定义 |
| 工具调用 | 读文件、写文件、执行命令 |
| 计划模式 | `/plan` 先出方案，确认后执行 |
| 会话管理 | 自动保存、`/resume` 恢复、`/clear` 重置 |
| 上下文管理 | 自动裁剪、token 估算 |
| 终端美化 | rich 排版、Markdown 渲染、状态栏 |

## 命令

```
/help      显示帮助
/status    当前状态
/model     切换模型
/provider  切换提供商
/persona   人格管理
/plan      计划模式
/tools     列出工具
/notools   工具开关
/clear     重置会话
/resume    恢复历史会话
/exit      退出
```

## 配置

`config.yaml` 支持多 provider：

```yaml
providers:
  deepseek:
    api_key: sk-xxx
    base_url: https://api.deepseek.com
    default_model: deepseek-chat
  mimo:
    api_key: sk-xxx
    base_url: https://api.mimiai.com
    default_model: mimo-v2.5-pro
```

## 项目结构

```
myagent/
├── main.py              # CLI 入口
├── agent.py             # Agent 核心（循环、上下文、工具调度）
├── tools.py             # 工具定义（读写文件、执行命令）
├── config.py            # 配置加载
├── system_prompt.py     # 系统提示词
├── persona.py           # 人格管理
├── personas/            # 人格文件（YAML）
├── sessions/            # 会话历史
└── logs/                # 工具日志
```

## 许可证

MIT
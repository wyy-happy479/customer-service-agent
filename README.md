# 🤖 多工具智能客服 Agent

基于 LangChain + OpenAI Function Calling 的智能客服系统，集成 **6 个工具**（订单查询、物流追踪、退款政策 RAG、工单创建、订单取消），实现 **7 项生产级特性**（Tool Routing + 权限分级 + 幂等 + 重试 + Human-in-the-Loop + 审计日志 + 参数校验）。

---

## 🎯 功能概览

| 工具 | 功能 | 数据来源 | 权限 | 风险 |
|------|------|---------|------|------|
| `query_order` | 按订单号查订单详情 | SQLite | 📖 read | 🟢 低 |
| `query_orders_by_phone` | 按手机号查所有订单 | SQLite | 📖 read | 🟢 低 |
| `track_logistics` | 查物流进度 + 时间线 | SQLite | 📖 read | 🟢 低 |
| `search_refund_policy` | 退款/退货/换货政策咨询 | ChromaDB RAG | 📖 read | 🟢 低 |
| `create_ticket` | 创建售后工单 | SQLite | ✍️ write | 🟡 中 |
| `cancel_order` | 取消订单（需二次确认） | SQLite | 🗑️ delete | 🔴 高 |

## 🏗 架构

```
用户输入
  │
  ▼
┌──────────────────────────────────────────────────────────────┐
│                    Agent 循环（agent.py）                     │
│                                                              │
│  LangChain 负责（调库）：                                     │
│    ChatOpenAI + bind_tools() → LLM 交互 + Schema 生成        │
│    @tool 装饰器 → type hints + docstring → Function Calling  │
│    HumanMessage / ToolMessage → 消息格式标准化               │
│                                                              │
│  自定义层负责（生产特性）：                                    │
│    ① Tool Routing — 意图分类，缩小工具集                     │
│    ② Pydantic 参数校验                                      │
│    ③ Permission 检查 — read/write/delete/payment 四级        │
│    ④ Idempotency — 幂等键防重复操作                          │
│    ⑤ Retry Policy — tenacity 指数退避，区分可/不可重试       │
│    ⑥ Human-in-the-Loop — 高风险需用户确认                    │
│    ⑦ Audit Log — JSONL 全记录                               │
└──────────────────────────────────────────────────────────────┘
  │
  ▼
最终回复（自然语言）
```

**技术栈：** Python + LangChain + OpenAI SDK（千问 DashScope）+ ChromaDB + SQLite + Pydantic + tenacity + Streamlit（可选）

## 🚀 快速开始

### 1. 环境准备

```bash
cd D:\AgentStudy\works\03-customer-service-agent

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

在**系统环境变量**中设置 `OPENAI_API_KEY`（千问百炼 API Key），
或复制 `.env.example` 为 `.env` 并填入：

```bash
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=你的Key
```

### 3. 启动

```bash
# CLI 交互模式
python main.py

# 单次查询
python main.py --once "ORD-0001的快递到哪了？"

# 重新初始化数据库
python main.py --init-db

# 查看审计日志
python main.py --audit

# Web 界面（可选）
streamlit run app.py
```

## 📁 项目结构

```
03-customer-service-agent/
├── main.py                   # CLI 入口
├── app.py                    # Streamlit Web UI（可选）
├── agent.py                  # ★ 核心引擎：LangChain bind_tools + 7 项生产特性
├── tool_registry.py          # 工具注册表（LangChain @tool 装饰器）
├── database.py               # SQLite 数据库（订单/物流/工单）
├── validation.py             # Pydantic 参数校验
├── idempotency.py            # 幂等机制（防重复操作）
├── retry.py                  # 重试策略（tenacity 库）
├── audit.py                  # 审计日志（JSONL）
├── config.py                 # 全局配置
├── requirements.txt          # 依赖清单
├── .env.example              # 环境变量模板
├── .gitignore                # Git 忽略规则
├── README.md                 # 本文件
├── data/
│   ├── customer_service.db   # SQLite 数据库文件（自动生成）
│   ├── audit_log.jsonl       # 审计日志（自动生成）
│   └── chroma_rag/           # 退款政策 RAG 知识库（首次启动自动构建）
└── tools/
    ├── order_tools.py        # 订单查询
    ├── logistics_tools.py    # 物流追踪
    ├── refund_policy_tools.py # 退款政策 RAG (LangChain RecursiveTextSplitter + MultiQueryRetriever)
    ├── ticket_tools.py       # 工单创建
    └── cancel_order_tools.py # 取消订单（高风险确认）
```

## 🧪 测试用例

```bash
# 1. 查订单
python main.py --once "帮我查一下订单ORD-0001的详细信息"

# 2. 查物流
python main.py --once "ORD-0001的快递到哪了？"

# 3. 按手机号查所有订单
python main.py --once "我手机号13800138001，帮我查我的订单"

# 4. 多工具联动（先查订单再查物流）
python main.py --once "我手机13800138001，帮我查最近那个订单的物流"

# 5. 退款政策 RAG（语义搜索 + MultiQueryRetriever 多角度变体）
python main.py --once "我想退货，有什么条件？"

# 6. 口语化政策查询（测试语义理解 + Query Rewrite）
python main.py --once "我刚买了双鞋穿着小了想换个大的，怎么操作？"

# 7. 创建售后工单
python main.py --once "ORD-0004收到的东西坏了，我要投诉"

# 8. 参数校验（非法订单号会被 Pydantic 拦截）
python main.py --once "帮我查订单号是abc的订单"

# 9. 审计日志
python main.py --audit
```

## 📊 审计日志示例

每次工具调用自动记录：

```json
{
  "timestamp": "2026-06-25T16:55:35",
  "tool_name": "query_order",
  "params": {"order_id": "ORD-0001"},
  "result": {"success": true, "order": {...}},
  "duration_ms": 12.5,
  "success": true,
  "risk_level": "low",
  "permission": "read",
  "confirmed_by_user": false
}
```

## 🔑 核心设计决策

### ① 工具定义：LangChain @tool 装饰器 → 自动生成 Function Calling Schema

```python
# type hints + docstring → LLM 看到的 JSON Schema，不用手写 dict
@tool
def query_order(order_id: Annotated[str, "订单号，如 ORD-0001"]) -> str:
    """根据订单号查询单个订单的详细信息。"""
    ...

# 面试话术：
# "工具定义我用 LangChain 的 @tool 装饰器，type hints + docstring 自动生成
#  Function Calling JSON Schema，不用手写 parameters dict。这是标准生产模式。"
```

### ② Agent 循环：ChatOpenAI.bind_tools() → 自动处理消息格式

```python
llm = ChatOpenAI(model="qwen-plus", ...)
llm_with_tools = llm.bind_tools(tools)     # LangChain 自动注入 tool schemas
response = llm_with_tools.invoke(messages)  # 自动处理 tool_call 解析
```

不用手写 `client.chat.completions.create(messages=..., tools=...)` 和 JSON 解析。

### ③ RAG：LangChain RecursiveCharacterTextSplitter + MultiQueryRetriever

- **Chunking**：用 `RecursiveCharacterTextSplitter`（不用手写递归切分）
- **检索**：用 `MultiQueryRetriever` → LLM 生成多个变体 → 多路搜索 → 去重合并
- **Query Rewrite**：用 LangChain `ChatPromptTemplate | LLM | StrOutputParser` 管道

### ④ Retry：tenacity 库（Python 最成熟的重试库）

```python
retry_decorator = retry(
    retry=retry_if_exception(_is_retryable),         # 白名单策略
    stop=stop_after_attempt(3),                       # 最多 3 次
    wait=wait_exponential(multiplier=1, max=10),      # 指数退避 1s→2s→4s
)
```

不重复造轮子。可重试错误白名单：网络超时 / 503 / 限流 → 重试；参数错误 / 余额不足 → 立即失败。

### ⑤ Tool Routing（意图分类缩小工具集）

```
"查一下 ORD-0001" → 只发 4 个查询工具（精准）
"我要取消订单"   → 只发 2 个操作工具（精准）
"你好"          → 发全部 6 个（防误杀）
```

### ⑥ Permission（读/写/删/支付 四级权限）

| 权限 | 示例工具 | 执行策略 |
|------|---------|---------|
| 📖 read | query_order, track_logistics | 直接执行 |
| ✍️ write | create_ticket | 幂等保护 + 可重试 |
| 🗑️ delete | cancel_order | 需用户二次确认 |
| 💰 payment | （预留） | 需二次确认 + 金融级幂等 |

### ⑦ Human-in-the-Loop + Idempotency

- 高风险操作 → 暂停 → 用户输入"确认" → 才执行
- 写操作 → 幂等键 = MD5(tool_name + params) → 命中则返回缓存结果

---

## 📝 面试话术速查

| 模块 | 怎么说 |
|------|--------|
| **工具定义** | 用 LangChain `@tool` 装饰器，type hints + docstring 自动生成 Function Calling Schema |
| **Agent 循环** | `ChatOpenAI.bind_tools()` + `invoke()`，LangChain 做 LLM 交互 + 消息格式；自己封装 Tool Routing / 幂等 / 重试 / 审计 |
| **RAG** | `RecursiveCharacterTextSplitter` 切分 + `MultiQueryRetriever` 多角度变体搜索 + `ChatPromptTemplate` pipe 做 Query Rewrite |
| **重试** | `tenacity` 库，白名单策略 + 指数退避，不是所有错误都重试 |
| **幂等** | 写操作自动带幂等键，网络超时重试不会重复创建 |
| **权限** | 每个工具的元数据声明 permission level，执行时系统统一检查 |
| **审计** | JSONL 格式全量记录 tool_name / params / result / duration / permission / confirmed |

## 📚 延伸阅读

- 项目 1（`works/01project`）— 结构化信息抽取，Pydantic Schema 校验
- 项目 2（`works/rag-knowledge-base`）— 完整 RAG 知识库（混合检索 + Rerank + 评估）
- LangChain @tool 文档：https://python.langchain.com/docs/how_to/custom_tools/
- LangChain bind_tools 文档：https://python.langchain.com/docs/how_to/tool_calling/
- tenacity 文档：https://tenacity.readthedocs.io/
- Pydantic v2 文档：https://docs.pydantic.dev/latest/

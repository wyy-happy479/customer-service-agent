# 🤖 多工具智能客服 Agent

基于 LangChain + OpenAI Function Calling 的智能客服系统，集成 **6 个工具**，实现 **9 项生产级特性**（Tool Routing 三层路由 + tool_choice 动态策略 + 无依赖并行执行 + 权限分级 + 幂等 + 重试 + Human-in-the-Loop + 审计日志 + 参数校验）。

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
│    ① Tool Routing — 关键词 + LLM 语义 + 兜底，三层路由        │
│    ② tool_choice — 根据业务状态动态设置（auto/required/强制） │
│    ③ 并行执行 — 同轮多 tool_call → ThreadPoolExecutor 并发   │
│    ④ Pydantic 参数校验                                      │
│    ⑤ Permission 检查 — read/write/delete/payment 四级        │
│    ⑥ Idempotency — 幂等键防重复操作                          │
│    ⑦ Retry Policy — tenacity 指数退避，区分可/不可重试       │
│    ⑧ Human-in-the-Loop — 高风险需用户确认                    │
│    ⑨ Audit Log — JSONL 全记录                               │
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

# 7. 并行执行（同时查两个订单）
python main.py --once "帮我同时查ORD-0001和ORD-0002的订单"

# 8. LLM 语义路由（关键词未命中时的语义兜底）
python main.py --once "帮我把那个单子作废"

# 9. 创建售后工单
python main.py --once "ORD-0004收到的东西坏了，我要投诉"

# 10. 参数校验（非法订单号会被 Pydantic 拦截）
python main.py --once "帮我查订单号是abc的订单"

# 11. 审计日志
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

### ⑤ Tool Routing（三层路由：关键词 → LLM 语义 → 兜底）

第一层关键词（零成本，匹配 QUERY vs ACTION），兜不住时第二层 LLM 语义分类（有缓存），两层都失败才发全部工具。

```
"查ORD-0001"     → 关键词命中 → 4 个查询工具
"帮我把单子作废"  → 关键词未命中 → LLM 语义判断 → action → 2 个操作工具
"hello"          → 兜底 → 全部 6 个工具
```

### ⑥ tool_choice（根据业务状态动态设置）

不是写死的 if/else——根据当前对话状态决定：用户已确认高风险操作时强制指定工具名，工具集缩小到 1 个时用 `required` 不准闲聊，其余 `auto` 让 LLM 自主决定。

### ⑦ 并行执行（同轮多 tool_call 并发）

LLM 同一轮返回多个 tool_calls = 判定无依赖 → `ThreadPoolExecutor` 并发执行。跨轮 Agent 循环天然串行处理有依赖场景。依赖关系不需要代码显式判断——LLM 已经分好了。

### ⑧ Permission（读/写/删/支付 四级权限）

| 权限 | 示例工具 | 执行策略 |
|------|---------|---------|
| 📖 read | query_order, track_logistics | 直接执行 |
| ✍️ write | create_ticket | 幂等保护 + 可重试 |
| 🗑️ delete | cancel_order | 需用户二次确认 |
| 💰 payment | （预留） | 需二次确认 + 金融级幂等 |

### ⑨ Human-in-the-Loop + Idempotency

- 高风险操作 → 暂停 → 用户输入"确认" → 才执行
- 写操作 → 幂等键 = MD5(tool_name + params) → 命中则返回缓存结果

---

## 📝 面试话术速查

| 模块 | 怎么说 |
|------|--------|
| **工具定义** | 用 LangChain `@tool` 装饰器，type hints + docstring 自动生成 Function Calling Schema |
| **Agent 循环** | `ChatOpenAI.bind_tools()` + `invoke()`，LangChain 做 LLM 交互 + 消息格式；自己封装 Tool Routing / 并行 / 幂等 / 重试 / 审计 |
| **Tool Routing** | 三层路由——关键词（零成本）→ LLM 语义分类（兜底）→ 全部工具（防误杀），LLM 结果有缓存 |
| **tool_choice** | 根据业务状态动态设置——确认后强制指定工具名，单工具集用 required 不准闲聊，其余 auto |
| **并行/串行** | 同轮多 tool_call → `ThreadPoolExecutor` 并发；跨轮 Agent 循环天然串行；依赖关系 LLM 自己判断 |
| **RAG** | `RecursiveCharacterTextSplitter` 切分 + `MultiQueryRetriever` 多角度变体搜索 + `ChatPromptTemplate` pipe 做 Query Rewrite |
| **重试** | `tenacity` 库，白名单策略 + 指数退避，LLM 调用和工具执行两层都包了 |
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

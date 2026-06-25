# 🤖 多工具智能客服 Agent

基于 Function Calling 的智能客服系统，集成 **6 个工具**（订单查询、物流追踪、退款政策 RAG、工单创建、订单取消），实现 **Agent 循环 + 权限分级 + Human-in-the-Loop + 审计日志**。

---

## 🎯 功能概览

| 工具 | 功能 | 数据来源 | 风险等级 |
|------|------|---------|---------|
| `query_order` | 按订单号查订单详情 | SQLite | 🟢 低 |
| `query_orders_by_phone` | 按手机号查所有订单 | SQLite | 🟢 低 |
| `track_logistics` | 查物流进度 + 时间线 | SQLite（模拟） | 🟢 低 |
| `search_refund_policy` | 退款/退货/换货政策咨询 | ChromaDB RAG | 🟢 低 |
| `create_ticket` | 创建售后工单 | SQLite | 🟡 中 |
| `cancel_order` | 取消订单（需二次确认） | SQLite | 🔴 高 |

## 🏗 架构

```
用户输入
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│                  Agent 循环（agent.py）                   │
│                                                          │
│  while True:                                             │
│    ① Tool Routing — 意图分类，缩小工具集（4 个 or 2 个）  │
│    ② LLM 决策 — 从缩小后的工具集中选一个                  │
│    ③ 参数校验 — Pydantic Model 声明式校验                 │
│    ④ 权限检查 — READ/WRITE/DELETE/PAYMENT 四级           │
│    ⑤ 幂等检查 — 写操作防重复（idempotency key）           │
│    ⑥ 重试执行 — 可重试错误指数退避，不可重试立即失败      │
│    ⑦ 审计日志 — JSONL 记录（含权限 + 耗时 + 成功/失败）   │
│                                                          │
│    高风险？（DELETE/PAYMENT）→ 等用户输入「确认」          │
└──────────────────────────────────────────────────────────┘
  │
  ▼
最终回复（自然语言）

**技术栈：** Python + OpenAI SDK（千问百炼 DashScope）+ SQLite + ChromaDB + Pydantic + Streamlit（可选）

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
├── main.py                  # CLI 入口
├── app.py                   # Streamlit Web UI（可选）
├── agent.py                 # ★ 核心引擎：Agent 循环 + 7 项生产特性
├── tool_registry.py         # 工具注册表（Tool dataclass 内聚全部元数据）
├── database.py              # SQLite 数据库（订单/物流/工单）
├── validation.py            # Pydantic 参数校验
├── idempotency.py           # 幂等机制（防重复操作）
├── retry.py                 # 重试策略（可重试 vs 不可重试）
├── audit.py                 # 审计日志（JSONL）
├── config.py                # 全局配置
├── requirements.txt         # 依赖清单
├── .env.example             # 环境变量模板
├── .gitignore               # Git 忽略规则
├── README.md                # 本文件
├── data/
│   ├── customer_service.db  # SQLite 数据库文件（自动生成）
│   ├── audit_log.jsonl      # 审计日志（自动生成）
│   └── chroma_rag/          # 退款政策 RAG 知识库（首次启动自动构建）
└── tools/
    ├── order_tools.py       # 订单查询
    ├── logistics_tools.py   # 物流追踪
    ├── refund_policy_tools.py # 退款政策 RAG（Chunking + Embedding + ChromaDB 语义搜索）
    ├── ticket_tools.py      # 工单创建
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

# 5. 退款政策 RAG（语义搜索）
python main.py --once "我想退货，有什么条件？"

# 6. 口语化政策查询（测试语义理解）
python main.py --once "我刚买了双鞋穿着小了想换个大的，怎么操作？"

# 7. 创建售后工单
python main.py --once "ORD-0004收到的东西坏了，我要投诉"

# 8. 参数校验（非法订单号会被拦截）
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
  "confirmed_by_user": false
}
```

## 🔑 核心设计决策

### ① Tool Selection + Tool Routing（工具太多时模型容易选错）

6 个工具不算多，但当工具数量增长到 20+ 时，LLM 的语义选择准确率会明显下降。
解法：先用关键词匹配判断用户意图（QUERY 还是 ACTION），只发对应类别的工具给 LLM。

```
"查一下 ORD-0001" → 只发 4 个查询工具（精准）
"我要取消订单"   → 只发 2 个操作工具（精准）
"你好"          → 发全部 6 个（防误杀）
```

优势：零 LLM 调用成本、确定性路由、不会误杀（意图不明时兜底发全部）。

### ② Permission（读/写/删/支付 四级权限）

每个 Tool 声明自己的 `PermissionLevel`，执行时系统统一检查：

| 权限 | 示例工具 | 执行策略 |
|------|---------|---------|
| 📖 READ | query_order, track_logistics | 直接执行 |
| ✍️ WRITE | create_ticket | 幂等保护 + 可重试 |
| 🗑️ DELETE | cancel_order | 需用户二次确认 |
| 💰 PAYMENT | （预留） | 需用户二次确认 + 金融级幂等 |

权限不是 if/else 硬编码，而是 Tool 的元数据——加新工具不需要改 agent.py。

### ③ Idempotency（幂等 — 避免重复扣款/重复下单）

写操作自动携带幂等键（MD5(tool_name + params)），执行前检查：
- 幂等键未命中 → 正常执行 + 存结果
- 幂等键命中 → 直接返回缓存结果（不重复执行）

解决：网络超时后用户重试导致重复创建工单的问题。

### ④ Retry Policy（区分可重试和不可重试错误）

不是所有错误都适合重试：

| 错误类型 | 策略 | 示例 |
|---------|------|------|
| 🔄 可重试 | 指数退避，最多 3 次 | 网络超时、503 服务不可用 |
| ⛔ 不可重试 | 立即返回错误 | 参数校验失败、余额不足 |

使用白名单策略——只有明确列为可重试的错误才重试，其余一律立即失败。

### ⑤ Human-in-the-Loop（高风险需用户确认）

DELETE/PAYMENT 级别的工具执行前返回确认提示 → 等待用户输入"确认"→ 才真正执行。
LLM 可能误判意图，"我想取消"不一定是真的要取消。

### ⑥ Audit Log（记录工具名、参数、结果、耗时、权限、用户授权）

JSONL 格式，每条记录包含：timestamp, tool_name, params, result, duration_ms, success, risk_level, permission, confirmed_by_user。

### ⑦ 参数校验（Pydantic）

用 Pydantic Model 做声明式校验，和项目 1 结构化输出用同一工具链。每个工具的参数是一个 Pydantic class，类型 + 格式 + 必填一次定义。

---

## 📝 简历写法

> **多工具智能客服 Agent**
> - 基于 OpenAI Function Calling 实现 6 工具 Agent，覆盖订单查询、物流追踪、工单创建、政策咨询全场景
> - 自研 RAG 链路（Chunking + Embedding + ChromaDB 语义检索），千问 text-embedding-v3 向量化，支持口语化政策查询
> - 实现 Human-in-the-Loop 高风险确认 + Pydantic 参数校验 + JSONL 审计日志（Tool Call Trace）
> - 支持 CLI 和 Streamlit 双入口，Agent 循环内 LLM 自主决策工具调用策略

## 📚 延伸阅读

- 项目 1（`works/01project`）— 结构化信息抽取，Pydantic Schema 校验
- 项目 2（`works/rag-knowledge-base`）— 完整 RAG 知识库（混合检索 + Rerank + 评估）
- OpenAI Function Calling 文档：https://platform.openai.com/docs/guides/function-calling
- Pydantic v2 文档：https://docs.pydantic.dev/latest/

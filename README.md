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
┌─────────────────────────────────────┐
│          Agent 循环（agent.py）      │
│                                     │
│  while True:                        │
│    ① LLM 决策（调哪个工具？）        │
│    ② 你的代码执行工具               │
│    ③ 参数校验（Pydantic）           │
│    ④ 高风险？→ 等用户确认           │
│    ⑤ 审计日志（JSONL）              │
│    ⑥ 结果返回 LLM → 继续/回答       │
└─────────────────────────────────────┘
  │
  ▼
最终回复（自然语言）
```

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
├── app.py                   # Streamlit Web UI
├── agent.py                 # ★ 核心引擎：Agent 循环 + Human-in-the-Loop
├── tool_registry.py         # 工具注册表（定义 + 执行映射）
├── database.py              # SQLite 数据库（订单/物流/工单）
├── validation.py            # Pydantic 参数校验
├── audit.py                 # 审计日志（JSONL）
├── config.py                # 全局配置
├── requirements.txt         # 依赖清单
├── .env                     # 环境变量（API Key）
├── data/
│   ├── customer_service.db  # SQLite 数据库文件
│   ├── audit_log.jsonl      # 审计日志
│   └── chroma_rag/          # 退款政策 RAG 知识库（ChromaDB）
└── tools/
    ├── order_tools.py       # 订单查询
    ├── logistics_tools.py   # 物流追踪
    ├── refund_policy_tools.py # 退款政策 RAG（语义搜索）
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

### 为什么用 Pydantic 做校验而不是手写正则？

声明式 > 命令式。一个 class 同时定义了类型、格式、错误消息，加新工具只需 3 行代码。和项目 1 的结构化输出校验保持技术栈统一。

### 为什么 RAG 用语义搜索而不是关键词匹配？

用户说"换颜色"时，退款政策原文没有"颜色"这个词，但 Embedding 能理解它和"买错尺码"是同一类换货需求。语义搜索比关键词匹配更能应对口语化、多样化的用户表达。

### 为什么 Human-in-the-Loop？

取消订单是不可逆操作。LLM 可能误判用户意图（"我想取消"不一定是真的要取消），所以高风险操作必须经人类确认后才执行。这是 OpenAI/Anthropic 官方推荐的生产级最佳实践。

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

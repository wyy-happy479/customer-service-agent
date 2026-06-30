# 智能客服 Agent

## 概述

专业的电商智能客服 Skill，支持订单查询、物流追踪、退款政策咨询、售后工单创建和取消订单等完整客服流程。集成了 RAG 语义搜索、Human-in-the-Loop 高风险确认、幂等保护、审计日志等生产级特性。

---

## 触发条件

当用户消息匹配以下任一模式时激活此 Skill：

### 关键词触发（零成本，正则匹配）

| 场景 | 触发词 / 正则 |
|------|--------------|
| **查订单** | `查` `看` `多少` `详情` `信息` / `ORD-\d{4}` / `13xxxxxxxxx`（手机号） |
| **查物流** | `物流` `快递` `到哪` `在哪` `进度` |
| **退款政策** | `退.*条件` `退.*政策` `怎么退` `多久` `到账` `时效` `流程` `什么样` `能不能` |
| **创建工单** | `退[款货]` `换[货]` `投诉` `工单` `帮我.*创建` `帮我.*申请` `我要退` `我要换` |
| **取消订单** | `取消` `我要取消` `帮我取消` `不想要了` |

### 兜底触发（关键词未命中时）

用 LLM 做语义意图分类，将用户消息分为 `query`（查询）或 `action`（操作），然后加载对应工具集。

---

## 工具链

```
┌────────────────────────────────────────────────────────────┐
│                     🔍 查询类工具 (READ)                     │
│                                                            │
│  query_order              query_orders_by_phone            │
│  ├─ 参数: order_id (ORD-XXXX)    ├─ 参数: phone (11位手机号) │
│  ├─ 校验: Pydantic pattern       ├─ 校验: Pydantic field     │
│  │  pattern=r"^ORD-\d{4}$"       │  validator + re.match     │
│  ├─ 数据: SQLite orders 表       ├─ 数据: SQLite orders 表   │
│  └─ 输出: 订单详情 JSON           └─ 输出: 订单列表 JSON       │
│                                                            │
│  track_logistics           search_refund_policy (RAG)      │
│  ├─ 参数: order_id          ├─ 参数: query (自然语言)        │
│  ├─ 校验: Pydantic pattern  ├─ 流程:                         │
│  ├─ 数据: SQLite logistics  │  ① 指代消解 (context rewrite)  │
│  └─ 输出: 物流追踪 JSON      │  ② MultiQueryRetriever 多角度  │
│                             │  ③ ChromaDB 向量语义搜索       │
│                             └─ 输出: 政策片段 + 相似度 JSON    │
├────────────────────────────────────────────────────────────┤
│                    ✏️ 操作类工具 (WRITE)                      │
│                                                            │
│  create_ticket                                            │
│  ├─ 参数: order_id + ticket_type + description            │
│  ├─ 校验: Pydantic (pattern + min_length)                 │
│  ├─ 幂等: idempotency key 防重复创建                        │
│  ├─ 重试: tenacity 指数退避 (3次, 1s→2s→4s)               │
│  ├─ 数据: SQLite tickets 表 INSERT                        │
│  └─ 输出: 工单号 TK-XXXX                                   │
│                                                            │
│  cancel_order                    ⚠️ 高风险 (DELETE)         │
│  ├─ 第一阶段: 预检 → 返回 requires_confirmation=true        │
│  ├─ Human-in-the-Loop: 等待用户输入「确认」                   │
│  └─ 第二阶段: 确认后 → execute_cancel_order_confirmed()     │
└────────────────────────────────────────────────────────────┘
```

### 工具执行流水线（每个工具调用都经过）

```
① Pydantic 参数校验
   ↓ 通过
② 权限检查 (read/write/delete 日志记录)
   ↓
③ 幂等检查 (写操作检查 idempotency key)
   ↓ 未命中
④ 执行 + tenacity 重试 (指数退避, 最多3次)
   ↓
⑤ 存幂等结果 (写操作)
   ↓
⑥ 审计日志 (JSONL 写入)
```

### Tool Routing（意图路由）

缩小每次 LLM 调用时的候选工具集，降低选错工具的概率：

```
用户消息
   ↓
第一层：关键词正则匹配 → 命中 → 返回 query_tools 或 action_tools
   ↓ 未命中
第二层：LLM 语义分类 → 返回对应工具集
   ↓ 失败
第三层：返回全部工具（兜底）
```

### Human-in-the-Loop 流程

```
用户说"取消 ORD-0001"
   ↓
LLM → tool_use(name="cancel_order", order_id="ORD-0001")
   ↓
tool 返回 {"requires_confirmation": true, "message": "⚠️ 高风险操作确认..."}
   ↓
Agent → 展示确认提示 → 等待用户输入
   ↓
用户输入「确认」→ execute_cancel_order_confirmed()
用户输入其他   → 返回"操作已取消"
```

---

## 执行机制：SKILL.md 如何与实际工具连接

### 先分清两层：SKILL.md 是说明书，不是执行器

```
┌──────────────────────────────────────────────────────────────┐
│  SKILL.md 做的事:                                              │
│    告诉 LLM "什么场景 → 什么工具 → 什么输出格式"                │
│                                                              │
│  它不包含任何可执行代码。它是一份给 LLM 看的操作手册。           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  工具执行做的事:                                               │
│    真正读写数据、调 API、执行逻辑                               │
│                                                              │
│  工具注册在 tool_registry.py（LangChain @tool），               │
│  或暴露为 MCP Server，或直接用 CLI 命令。                      │
│  工具的实现代码在 tools/ 目录下。                              │
└──────────────────────────────────────────────────────────────┘
```

### Skill 加载：两阶段机制

```
阶段一（会话开始，自动注入）

  system prompt 里出现:
    "可用 Skill:
     - 智能客服 Agent: 订单查询、物流追踪、退款政策咨询、售后工单..."
    
  此时只注入了 name + description（几十个 token）。
  LLM 知道有这个 Skill 存在，但不知道具体怎么操作。

                ↓ 用户消息匹配触发条件

阶段二（触发时，调用 Skill 工具）

  用户说 "我的 ORD-0001 到哪了"
    → 匹配触发词 "物流" "ORD-0001"
    → Claude Code 把 SKILL.md 全文注入 system prompt
    → LLM 现在知道了:
        ✅ 用哪个工具 (track_logistics)
        ✅ 参数格式 (order_id: ORD-XXXX)
        ✅ 回复模板 (📦 订单 {id} 物流进度...)
```

### 当前项目 03 的实际执行路径

项目 03 自身是一个完整的 Agent 应用，有独立的 Agent 循环，**不依赖外部框架来驱动工具执行**：

```
python main.py  ← 启动项目自己的 Agent 循环
    │
    ▼
CustomerServiceAgent.chat("我的订单 ORD-0001 到哪了？")
    │
    ▼
LLM 推理（LangChain ChatOpenAI + bind_tools(ALL_TOOLS)）
    │  ← 工具通过 @tool 装饰器直接注册，LLM 通过 Function Calling 原生选工具
    ▼
LLM 输出: tool_use(name="track_logistics", args={order_id: "ORD-0001"})
    │  ← LangChain 自动解析 tool_use，调用对应的 @tool 函数
    ▼
execute_track_logistics() → SQLite 查 logistics 表 → 返回 JSON
    │
    ▼
结果传回 LLM → LLM 按 system prompt 里的输出模板格式化 → 回答用户
```

**关键：这个流程里 SKILL.md 不是必需品。** SKILL.md 是给"外部 Agent 框架（如 Claude Code）来驱动这个项目"时用的说明书。项目自己跑的时候，工具链由 `tool_registry.py` + `agent.py` 管理。

### 如果要让 Claude Code 驱动这个项目：两条路径

#### 路径 A：MCP Server（推荐，生产级）

把 `tools/` 下的 6 个 `execute_*` 函数暴露为 MCP Tool：

```
Claude Code（外部 Agent 框架）
    │
    │  system prompt 注入 SKILL.md 全文 → LLM 知道"查物流用 track_logistics"
    │
    ▼
LLM 输出: tool_use(name="mcp__track_logistics", args={order_id: "ORD-0001"})
    │  ← 这是 MCP 协议的标准 tool call，不是 Bash 命令
    ▼
MCP Client → JSON-RPC → MCP Server（包装了 execute_track_logistics）
    │
    ▼
execute_track_logistics() 正常执行 → 结果原路返回
```

**优势：**
- LLM 不需要知道 Python 文件路径、不需要拼命令——只知道工具名
- MCP 协议自带参数 JSON Schema 校验
- 复用项目现有的 `execute_*` 函数，0 改动
- 幂等、审计、重试等生产特性全部保留（因为走的是同一套代码）

#### 路径 B：直接用 CLI / SQLite（轻量，但绕过生产特性）

不经过 Python 代码，直接用 SQLite 命令行查数据库：

```
Claude Code
    │
    ▼
LLM 输出: Bash(command="sqlite3 data/customer_service.db
           \"SELECT * FROM logistics WHERE order_id='ORD-0001'\"")
    │
    ▼
Bash 执行 sqlite3 → 返回表格文本
```

**代价：**
- ⚠️ 绕过了 Pydantic 参数校验（没有格式检查）
- ⚠️ 绕过了幂等保护（重复执行会怎样？）
- ⚠️ 绕过了审计日志（没有 JSONL 记录）
- ⚠️ 取消了高风险操作无法走 Human-in-the-Loop 确认流程

**适用场景：** 临时调试、快速查看数据。不适合生产。

### 总结：SKILL.md 和工具的关系

```
                     SKILL.md
                  （纯文本说明书）
                        │
                        │ 注入 system prompt
                        ▼
用户输入 ──→ LLM 推理 ──→ tool_use ──→ 执行层 ──→ tool_result ──→ 格式化回答
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
          LangChain      MCP Server      Bash + CLI
          @tool 函数      (推荐)          (轻量)
          
          项目 03 自己     项目 03 被      项目 03 被
          跑的时候用的     Claude Code     Claude Code
          （原生路径）     驱动时推荐用    直接查 SQLite
```

**SKILL.md 只是说明书。真正干活的是工具执行层。说明书告诉 LLM"遇到什么情况该拿哪把刀"——但刀本身在工具层，不在说明书里。**

---

## 输出模板

---

## 输出模板

### 查订单成功

```
✅ 订单 ORD-0001 详情

商品：机械键盘 K99
金额：¥299.00
状态：已发货
下单时间：2025-06-20 10:30

如需查看物流进度，请告诉我。
```

### 查物流成功

```
📦 订单 ORD-0001 物流进度

快递公司：顺丰速运
运单号：SF1234567890
当前位置：北京分拣中心
状态：运输中

时间线：
  ● 2025-06-20 18:00  已揽收（深圳龙华网点）
  ● 2025-06-21 02:00  已到达中转站（广州分拣中心）
  ● 2025-06-22 08:00  运输中（北京分拣中心）
```

### 退款政策 RAG 查询

```
📚 关于「7天无理由退货」

[相似度 92%]
购买后7天内，在商品完好、不影响二次销售的前提下，可申请无理由退货。
退回运费由买家承担。如因商品质量问题导致的退货，退回运费由卖家承担。

[相似度 85%]
以下商品类型不支持7天无理由退货：
1. 定制类商品...
2. 生鲜食品...
...

如果您需要为某个订单申请售后，请提供订单号。
```

### 创建工单成功 / 失败

```
✅ 工单创建成功
工单号：TK-0002
类型：退款
客服将在 24 小时内与您联系处理。

---

❌ 工单创建失败
原因：工单类型「xxx」无效。可选类型：refund / exchange / complaint
```

### 取消订单 — 高风险确认

```
⚠️ 高风险操作确认

订单：ORD-0003
商品：27寸显示器 4K
金额：¥2,499.00
当前状态：待发货

取消订单后无法恢复，是否确认取消？
请输入「确认」继续，或输入其他内容放弃操作。
```

### 无结果 / 错误

```
❌ 未找到订单 ORD-9999。请确认订单号是否正确。

---

❌ 订单号格式错误。「order_id」应为 ORD-XXXX（4位数字），如 ORD-0001
```

---

## 防护层

| 层级 | 机制 | 说明 |
|------|------|------|
| **输入校验** | Pydantic Field(pattern=...) | 订单号 / 手机号格式校验，非法参数直接拒绝 |
| **参数清洗** | strip().upper() + field_validator | 去空格、统一大小写、去横线 |
| **权限分级** | read / write / delete / payment | 每次调用记录权限级别 |
| **风险分级** | low / medium / high | high 级别触发 Human-in-the-Loop |
| **幂等保护** | MD5 hash + TTL 内存缓存 | 写操作防止网络重试导致重复创建 |
| **重试策略** | tenacity 指数退避 3 次 | 网络错误自动重试，逻辑错误立即失败 |
| **输出截断** | 各工具返回精简 JSON | 防止撑爆 LLM 上下文窗口 |
| **审计日志** | JSONL 追加写入 | 全量记录：时间、工具、参数、结果、耗时、成功/失败、风险等级 |
| **最大轮数** | max_iterations=10 | 防止 Agent 无限循环 |

---

## 配置项

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | qwen-plus | LLM 模型（千问百炼 DashScope，兼容 OpenAI 接口） |
| `AGENT_CONFIG.max_iterations` | 10 | Agent 最多连续调几次工具 |
| `RAG_CHROMA_PATH` | data/chroma_rag | 退款政策向量库存储路径 |
| `CHUNK_SIZE` | 300 | RAG 文档切分大小 |
| `CHUNK_OVERLAP` | 50 | 切分重叠大小 |
| `TOP_K` | 3 | RAG 检索返回条数 |
| `IDEMPOTENCY_TTL` | 3600s | 幂等记录保留时间 |
| `RETRY.max_retries` | 3 | tenacity 最大重试次数 |

---

## 依赖库

```
anthropic              # LLM API
langchain-core         # 工具抽象 + bind_tools()
langchain-openai       # ChatOpenAI 适配千问
langchain-text-splitters  # RAG 文档切分
langchain.retrievers   # MultiQueryRetriever
chromadb               # 向量存储
pydantic               # 参数校验
tenacity               # 重试策略
python-dotenv          # 环境变量管理
```

---

## 配套资源

```
03-customer-service-agent/
│
├── .claude/skills/customer-service/  ← Skill 文件夹（本文件所在）
│   ├── SKILL.md                      # 本文件：Skill 规格说明
│   ├── scripts/                      # 可执行辅助脚本
│   │   ├── check_tools.py            # 工具可用性自检
│   │   └── reset_db.py               # 重置数据库 + RAG 索引
│   ├── references/                   # 参考资料
│   │   ├── database_schema.md        # 数据库表结构 + 模拟数据
│   │   └── refund_policy.md          # 退款政策源文档（RAG 素材）
│   ├── templates/                    # 回复模板
│   │   └── response_templates.md     # 所有场景的输出模板 + 状态映射
│   └── assets/                       # 辅助资源
│       └── config_reference.md       # 全部配置项速查
│
├── main.py                       ← CLI 入口
├── app.py                        ← Streamlit Web UI 入口
├── agent.py                      ← Agent 核心引擎
├── tool_registry.py              ← 工具注册 + 路由 + 元数据
├── validation.py                 ← Pydantic 参数校验
├── audit.py                      ← JSONL 审计日志
├── idempotency.py                ← 幂等保护
├── retry_policy.py               ← tenacity 重试策略
├── database.py                   ← SQLite 数据访问层
├── config.py                     ← 集中配置管理
├── tools/                        ← 工具实现层
│   ├── order_tools.py            # 订单查询
│   ├── logistics_tools.py        # 物流追踪
│   ├── refund_policy_tools.py    # 退款政策 RAG
│   ├── ticket_tools.py           # 工单创建
│   └── cancel_order_tools.py     # 取消订单（高风险）
│
├── data/                         ← 运行时数据（不提交 Git）
│   ├── customer_service.db       # SQLite 数据库
│   ├── chroma_rag/               # ChromaDB 向量存储
│   └── audit_log.jsonl           # 审计日志
│
├── .env                          ← 环境变量（不提交 Git）
└── .env.example                  ← 环境变量模板（已提交）
```

### scripts/ — 可执行辅助脚本

| 脚本 | 用途 | 命令 |
|------|------|------|
| `check_tools.py` | 逐一测试每个 Tool 的可用性（参数校验 + 执行） | `python .claude/skills/customer-service/scripts/check_tools.py` |
| `reset_db.py` | 删除旧数据库和 RAG 索引，重新初始化 | `python .claude/skills/customer-service/scripts/reset_db.py` |

### references/ — 参考资料

| 文件 | 内容 | 用途 |
|------|------|------|
| `database_schema.md` | 三张表的完整 DDL + 模拟数据 | 开发/调试时快速了解数据结构 |
| `refund_policy.md` | 退款政策全文 | RAG 知识库的源素材；修改后需重建 ChromaDB |

### templates/ — 回复模板

| 文件 | 内容 |
|------|------|
| `response_templates.md` | 8 种场景的输出模板 + 状态/工单类型的映射表 |

### assets/ — 辅助资源

| 文件 | 内容 |
|------|------|
| `config_reference.md` | LLM / Agent / RAG / 重试 配置项速查 |

---

## 启动方式

```bash
# 交互模式（CLI）
python main.py

# 单次查询
python main.py --once "我的订单ORD-0001到哪了"

# 审计日志
python main.py --audit

# Web UI
streamlit run app.py

# 工具自检
python .claude/skills/customer-service/scripts/check_tools.py

# 重置数据库
python .claude/skills/customer-service/scripts/reset_db.py
```

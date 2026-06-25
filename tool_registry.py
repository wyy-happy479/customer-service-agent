"""
工具注册表 — 按使用场景组织

📖 核心概念：
    每个工具不只是"名字 + 描述"，它有完整的身份：
    - 属于哪个场景（查信息？改数据？）
    - 权限层级（只读？写？删？支付？）
    - 风险有多高（只读？可撤回？不可逆？）
    - LLM 看什么（JSON Schema）
    - 你的代码执行什么（Python 函数）

    所有信息内聚在一起，加一个新工具只改这一个文件。

🔍 底层原理：
    Tool 这个 dataclass 把每个工具的"定义 + 执行 + 权限 + 风险 + 场景"绑在一起。
    TOOLS 列表 = 面向 LLM 的 tool_definitions + 面向你代码的执行映射 + 面向运维的权限分级。

🆚 Tool Selection vs Tool Routing：
    - Tool Selection 问题：工具太多 → LLM 选择准确率下降（6 个还好，20+ 就会出问题）
    - Tool Routing 解法：先用前置分类缩小候选集，再让 LLM 从缩小后的集合里选
    - 本项目的实现：route_tools() 根据用户意图关键词缩小到 QUERY 或 ACTION 子集
"""

from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum
import re

from tools.order_tools import execute_query_order, execute_query_orders_by_phone
from tools.logistics_tools import execute_track_logistics
from tools.refund_policy_tools import get_rag_engine
from tools.ticket_tools import execute_create_ticket
from tools.cancel_order_tools import execute_cancel_order, execute_cancel_order_confirmed


# ── 前向声明：RAG 搜索函数（Tool 定义里引用了它）────────

def _execute_search_refund_policy(params: dict) -> dict:
    """RAG 退款政策语义搜索（ChromaDB + Embedding）"""
    import json
    query = params.get("query", "")
    rag = get_rag_engine()
    result_str = rag.search(query)
    return json.loads(result_str)


# ═══════════════════════════════════════════════════════════
# 分类枚举
# ═══════════════════════════════════════════════════════════

class ToolCategory(str, Enum):
    """工具按业务场景分类"""
    QUERY = "query"          # 🔍 查询类：只读，不修改任何数据
    ACTION = "action"        # ✏️  操作类：会修改数据


class PermissionLevel(str, Enum):
    """
    权限层级 — 每个工具必须声明自己的权限需求。
    借鉴 Unix 文件权限（rwx）的思路，按操作类型分层。

    面试亮点：权限不是在代码里用 if/else 硬编码，而是 Tool 的元数据，
    执行层统一校验——加一个新工具不需要改 agent.py 里的权限逻辑。
    """
    READ = "read"            # 📖 读：只能查数据，无任何副作用
    WRITE = "write"          # ✍️  写：会创建/修改数据，但可撤回
    DELETE = "delete"        # 🗑️  删：不可逆删除，需用户确认
    # 当前项目没有真实支付，但架构预留，面试时可以说"支持扩展"
    PAYMENT = "payment"      # 💰 支付：涉及资金操作，需二次确认


class RiskLevel(str, Enum):
    """工具风险等级（面向 Agent 决策，Permission 面向系统强制）"""
    LOW = "low"              # 🟢 只读查询，无副作用
    MEDIUM = "medium"        # 🟡 有副作用但可撤回
    HIGH = "high"            # 🔴 不可逆，需用户二次确认


# ═══════════════════════════════════════════════════════════
# 工具定义（一个 dataclass 内聚全部信息）
# ═══════════════════════════════════════════════════════════

@dataclass
class Tool:
    name: str                                          # 工具名
    description: str                                   # 自然语言描述（LLM 语义匹配依据）
    category: ToolCategory                             # 业务场景：查询 | 操作
    permission: PermissionLevel                        # 权限层级：读 | 写 | 删 | 支付
    risk_level: RiskLevel                              # 风险等级：低 | 中 | 高
    parameters: dict                                   # JSON Schema 参数定义
    required: list[str] = field(default_factory=list)  # 必填参数
    executor: Callable[[dict], dict] | None = None     # 执行函数（你的代码）
    high_risk_executor: Callable[[dict], dict] | None = None  # 高风险确认后的真正执行

    def to_openai_format(self) -> dict:
        """转成 OpenAI Function Calling 的标准格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                }
            }
        }


# ═══════════════════════════════════════════════════════════
# 6 个工具 — 按场景 + 权限分级
# ═══════════════════════════════════════════════════════════

# ── 🔍 查询类：Permission.READ，RiskLevel.LOW ──────────

TOOL_QUERY_ORDER = Tool(
    name="query_order",
    description="根据订单号查询单个订单的详细信息，包括商品名、金额、订单状态、下单时间。"
                "当用户询问某个具体订单时使用。",
    category=ToolCategory.QUERY,
    permission=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    parameters={
        "order_id": {
            "type": "string",
            "description": "订单号，格式为 ORD-XXXX（4位数字），如 ORD-0001"
        }
    },
    required=["order_id"],
    executor=execute_query_order,
)

TOOL_QUERY_ORDERS_BY_PHONE = Tool(
    name="query_orders_by_phone",
    description="根据手机号查询该用户的所有订单。当用户问'我的订单'但没有提供订单号时，"
                "先用这个工具查出该用户的所有订单，再展示给用户。",
    category=ToolCategory.QUERY,
    permission=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    parameters={
        "phone": {
            "type": "string",
            "description": "11位中国大陆手机号，如 13800138000"
        }
    },
    required=["phone"],
    executor=execute_query_orders_by_phone,
)

TOOL_TRACK_LOGISTICS = Tool(
    name="track_logistics",
    description="根据订单号查询物流信息，包括快递公司、运单号、当前位置、完整物流时间线。"
                "当用户问'我的快递到哪了'或'物流进度'时使用。",
    category=ToolCategory.QUERY,
    permission=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    parameters={
        "order_id": {
            "type": "string",
            "description": "订单号，格式为 ORD-XXXX"
        }
    },
    required=["order_id"],
    executor=execute_track_logistics,
)

TOOL_SEARCH_REFUND_POLICY = Tool(
    name="search_refund_policy",
    description="搜索退款/退货/换货/售后政策。当用户询问退款规则、退货条件、换货流程、"
                "退款时效等政策性问题时使用。这些是静态政策信息，不涉及具体订单。",
    category=ToolCategory.QUERY,
    permission=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    parameters={
        "query": {
            "type": "string",
            "description": "用户的政策问题，如'7天无理由退货的条件'、'退款多久到账'"
        }
    },
    required=["query"],
    executor=_execute_search_refund_policy,
)

# ── ✏️ 操作类：WRITE/DELETE，需要权限检查 ──────────────

TOOL_CREATE_TICKET = Tool(
    name="create_ticket",
    description="为订单创建售后工单（退款/换货/投诉）。当用户明确要求退款、换货或投诉时使用。"
                "注意：创建工单不代表自动退款，工单创建后由人工客服处理。",
    category=ToolCategory.ACTION,
    permission=PermissionLevel.WRITE,
    risk_level=RiskLevel.MEDIUM,
    parameters={
        "order_id": {
            "type": "string",
            "description": "订单号，格式为 ORD-XXXX"
        },
        "ticket_type": {
            "type": "string",
            "enum": ["refund", "exchange", "complaint"],
            "description": "工单类型：refund=退款, exchange=换货, complaint=投诉"
        },
        "description": {
            "type": "string",
            "description": "问题描述，如'收到的商品外包装破损'"
        }
    },
    required=["order_id", "ticket_type", "description"],
    executor=execute_create_ticket,
)

TOOL_CANCEL_ORDER = Tool(
    name="cancel_order",
    description="取消指定订单。⚠️ 这是一个不可逆操作！执行前需要用户二次确认。"
                "只有 pending（待发货）状态的订单可以取消。已发货的订单无法取消。",
    category=ToolCategory.ACTION,
    permission=PermissionLevel.DELETE,
    risk_level=RiskLevel.HIGH,
    parameters={
        "order_id": {
            "type": "string",
            "description": "要取消的订单号，格式为 ORD-XXXX"
        }
    },
    required=["order_id"],
    executor=execute_cancel_order,
    high_risk_executor=lambda params: execute_cancel_order_confirmed(
        params.get("order_id", "")
    ),
)


# ═══════════════════════════════════════════════════════════
# 工具全集
# ═══════════════════════════════════════════════════════════

TOOLS: list[Tool] = [
    # 🔍 查询类（Permission.READ）
    TOOL_QUERY_ORDER,
    TOOL_QUERY_ORDERS_BY_PHONE,
    TOOL_TRACK_LOGISTICS,
    TOOL_SEARCH_REFUND_POLICY,
    # ✏️ 操作类（Permission.WRITE / DELETE）
    TOOL_CREATE_TICKET,
    TOOL_CANCEL_ORDER,
]

# 全部工具（用于兜底）
TOOL_DEFINITIONS_ALL: list[dict] = [t.to_openai_format() for t in TOOLS]


# ═══════════════════════════════════════════════════════════
# ① Tool Routing：根据用户意图缩小工具集
# ═══════════════════════════════════════════════════════════

# 意图关键词 → 只发送对应类别的工具
# 不是用 LLM 分类（太重），而是关键词匹配（快、确定性高、零成本）
# 这个方案在中文客服场景下足够用，因为用户意图通常很明确
INTENT_PATTERNS: dict[ToolCategory, str] = {
    ToolCategory.QUERY: r"查|看|多少|到哪|在哪|物流|快递|进度|详情|信息|政策|规则|条件|"
                         r"退.*条件|退.*政策|怎么退|多久|什么样|能不能|可以不|有没有",
    ToolCategory.ACTION: r"取消|退[款货]|换[货]|投诉|工单|帮我.*创建|帮我.*申请|"
                         r"我要退|我要换|我要取消|我要投诉|给我退|给我换|帮我退|帮我换",
}


def route_tools(user_message: str, verbose: bool = False) -> list[dict]:
    """
    Tool Routing：根据用户意图缩小发给 LLM 的工具集。

    原理：
    1. 用关键词匹配判断用户意图属于 QUERY 还是 ACTION
    2. 只发送对应类别的工具（4 个而不是 6 个）
    3. 如果匹配不上 → 防误杀：发送全部工具

    为什么这很重要：
    - LLM 需要从工具列表中做"语义选择"，工具越多准确率越低
    - 6 个工具还好，但 20+ 个时 LLM 开始混淆
    - 前置缩小候选集 = 减少 LLM 选错工具的概率

    面试话术：
    "我用了一个轻量级的 intent-based tool routing——不是让 LLM 从 20 个工具里选，
     而是先用关键词匹配缩小到 3-4 个候选，再让 LLM 精确选择。
     这比让 LLM 做所有事更快、更便宜、更可靠。"
    """
    for category, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, user_message):
            filtered = [t.to_openai_format() for t in TOOLS if t.category == category]
            if verbose:
                print(f"  🎯 Tool Routing: 意图={category.value} → "
                      f"发送 {len(filtered)}/{len(TOOLS)} 个工具")
            return filtered

    # 防误杀：意图不明时发送全部
    if verbose:
        print(f"  🎯 Tool Routing: 意图未识别 → 发送全部 {len(TOOLS)} 个工具")
    return TOOL_DEFINITIONS_ALL


# ═══════════════════════════════════════════════════════════
# ② 自动生成的派生结构（从 TOOLS 列表推导，不用手动维护）
# ═══════════════════════════════════════════════════════════

TOOL_EXECUTORS: dict[str, Callable[[dict], dict]] = {
    t.name: t.executor for t in TOOLS if t.executor is not None
}

HIGH_RISK_EXECUTORS: dict[str, Callable[[dict], dict]] = {
    t.name: t.high_risk_executor
    for t in TOOLS
    if t.risk_level == RiskLevel.HIGH and t.high_risk_executor is not None
}

# 权限映射：PermissionLevel → 需要的用户确认级别
PERMISSION_REQUIRES_CONFIRMATION: set[PermissionLevel] = {
    PermissionLevel.DELETE,
    PermissionLevel.PAYMENT,
}


# ═══════════════════════════════════════════════════════════
# ③ 查询函数
# ═══════════════════════════════════════════════════════════

def get_tool(name: str) -> Tool | None:
    for t in TOOLS:
        if t.name == name:
            return t
    return None


def get_risk_level(tool_name: str) -> str:
    tool = get_tool(tool_name)
    return tool.risk_level.value if tool else "low"


def get_permission(tool_name: str) -> PermissionLevel:
    tool = get_tool(tool_name)
    return tool.permission if tool else PermissionLevel.READ


def is_high_risk(tool_name: str) -> bool:
    tool = get_tool(tool_name)
    return tool is not None and tool.risk_level == RiskLevel.HIGH


def requires_confirmation(tool_name: str) -> bool:
    """判断工具执行前是否需要用户确认"""
    tool = get_tool(tool_name)
    if tool is None:
        return False
    return tool.permission in PERMISSION_REQUIRES_CONFIRMATION


def get_tools_by_category(category: ToolCategory) -> list[Tool]:
    return [t for t in TOOLS if t.category == category]


def execute_high_risk_confirmed(tool_name: str, params: dict) -> dict:
    executor = HIGH_RISK_EXECUTORS.get(tool_name)
    if executor is None:
        return {"success": False, "message": f"未知的高风险工具: {tool_name}"}
    return executor(params)


# ═══════════════════════════════════════════════════════════
# 打印工具清单
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("📋 工具注册表")
    print("=" * 60)

    for cat in ToolCategory:
        tools = get_tools_by_category(cat)
        print(f"\n{'🔍' if cat == ToolCategory.QUERY else '✏️'}  {cat.value.upper()} ({len(tools)} 个)：")
        for t in tools:
            risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}[t.risk_level.value]
            perm_icon = {"read": "📖", "write": "✍️", "delete": "🗑️", "payment": "💰"}[t.permission.value]
            print(f"  {risk_icon} {perm_icon} {t.name}")
            print(f"     {t.description[:80]}...")

    print(f"\n📊 总计: {len(TOOLS)} 个工具")
    print(f"   查询类: {len(get_tools_by_category(ToolCategory.QUERY))} 个")
    print(f"   操作类: {len(get_tools_by_category(ToolCategory.ACTION))} 个")

    print("\n🧪 Tool Routing 测试：")
    for msg in [
        "查一下ORD-0001", "我的快递到哪了", "退款政策是什么",
        "我要取消订单", "帮我创建工单", "你好",
    ]:
        result = route_tools(msg)
        print(f"  '{msg}' → 发送 {len(result)}/{len(TOOLS)} 个工具")

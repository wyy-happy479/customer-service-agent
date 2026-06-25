"""
工具注册表 — 基于 LangChain @tool 装饰器

📖 核心概念：
    用 LangChain 的 @tool 装饰器定义工具。@tool 自动从函数的
    docstring + type hints 生成 OpenAI Function Calling 的 JSON Schema，
    不再需要手写 dict。

🔍 之前 vs 现在：

    之前（手写）：
        TOOL_QUERY_ORDER = Tool(
            name="query_order",
            description="根据订单号查询...",
            parameters={...},     # 手写 JSON Schema
            required=[...],       # 手写 required 列表
            executor=...,         # 手写函数映射
        )

    现在（@tool）：
        @tool
        def query_order(order_id: str) -> str:
            '''根据订单号查询单个订单的详细信息。'''
            ...                   # docstring 自动变 description
                                  # type hints 自动变 parameters schema

💡 为什么生产环境用 @tool：
    1. Schema 自动生成 — type hint + docstring → JSON Schema，不用手写
    2. 类型安全 — str 参数传了 int IDE 会报红
    3. 面试加分 — "我用 LangChain 的 @tool 定义工具，自动生成 Function Calling Schema"
    4. 加工具只需一个函数 — 不用同时维护 definition dict + executor dict
"""

from typing import Annotated
from langchain_core.tools import tool

from tools.order_tools import execute_query_order, execute_query_orders_by_phone
from tools.logistics_tools import execute_track_logistics
from tools.refund_policy_tools import get_rag_engine
from tools.ticket_tools import execute_create_ticket
from tools.cancel_order_tools import execute_cancel_order, execute_cancel_order_confirmed


# ═══════════════════════════════════════════════════════════
# 🔍 查询类工具（READ）
# ═══════════════════════════════════════════════════════════

@tool
def query_order(order_id: Annotated[str, "订单号，格式为 ORD-XXXX（4位数字），如 ORD-0001"]) -> str:
    """根据订单号查询单个订单的详细信息，包括商品名、金额、订单状态、下单时间。
    当用户询问某个具体订单时使用。"""
    import json
    result = execute_query_order({"order_id": order_id.strip().upper()})
    return json.dumps(result, ensure_ascii=False)


@tool
def query_orders_by_phone(phone: Annotated[str, "11位中国大陆手机号，如 13800138000"]) -> str:
    """根据手机号查询该用户的所有订单。当用户问'我的订单'但没有提供订单号时，
    先用这个工具查出该用户的所有订单，再展示给用户。"""
    import json
    result = execute_query_orders_by_phone({"phone": phone.strip()})
    return json.dumps(result, ensure_ascii=False)


@tool
def track_logistics(order_id: Annotated[str, "订单号，格式为 ORD-XXXX（4位数字）"]) -> str:
    """根据订单号查询物流信息，包括快递公司、运单号、当前位置、完整物流时间线。
    当用户问'我的快递到哪了'或'物流进度'时使用。"""
    import json
    result = execute_track_logistics({"order_id": order_id.strip().upper()})
    return json.dumps(result, ensure_ascii=False)


@tool
def search_refund_policy(query: Annotated[str, "用户的政策问题，如'7天无理由退货的条件'"]) -> str:
    """搜索退款/退货/换货/售后政策（基于 RAG 语义搜索）。
    当用户询问退款规则、退货条件、换货流程、退款时效等政策性问题时使用。"""
    rag = get_rag_engine()
    return rag.search(query)


# ═══════════════════════════════════════════════════════════
# ✏️  操作类工具（WRITE / DELETE）
# ═══════════════════════════════════════════════════════════

@tool
def create_ticket(
    order_id: Annotated[str, "订单号，格式为 ORD-XXXX"],
    ticket_type: Annotated[str, "工单类型：refund=退款, exchange=换货, complaint=投诉"],
    description: Annotated[str, "问题描述，如'收到的商品外包装破损'"],
) -> str:
    """为订单创建售后工单（退款/换货/投诉）。当用户明确要求退款、换货或投诉时使用。
    注意：创建工单不代表自动退款，工单创建后由人工客服处理。"""
    import json
    result = execute_create_ticket({
        "order_id": order_id.strip().upper(),
        "ticket_type": ticket_type.strip(),
        "description": description.strip(),
    })
    return json.dumps(result, ensure_ascii=False)


@tool
def cancel_order(order_id: Annotated[str, "要取消的订单号，格式为 ORD-XXXX"]) -> str:
    """取消指定订单。⚠️ 不可逆操作！只有 pending 状态的订单可取消。
    已发货的订单无法取消。执行前需要用户二次确认。"""
    import json
    result = execute_cancel_order({"order_id": order_id.strip().upper()})
    return json.dumps(result, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 工具集合 — 按场景分两类
# ═══════════════════════════════════════════════════════════

# 🔍 查询类（传给 route_tools 缩小候选集用）
QUERY_TOOLS = [
    query_order,
    query_orders_by_phone,
    track_logistics,
    search_refund_policy,
]

# ✏️ 操作类
ACTION_TOOLS = [
    create_ticket,
    cancel_order,
]

# 全部工具
ALL_TOOLS = QUERY_TOOLS + ACTION_TOOLS

# 工具名 → LangChain Tool 对象
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


# ═══════════════════════════════════════════════════════════
# 元数据：权限 + 风险 + 确认执行函数（@tool 不包含这些）
# ═══════════════════════════════════════════════════════════

TOOL_META = {
    # 🔍 查询类
    "query_order":             {"permission": "read",   "risk": "low",    "category": "query"},
    "query_orders_by_phone":   {"permission": "read",   "risk": "low",    "category": "query"},
    "track_logistics":         {"permission": "read",   "risk": "low",    "category": "query"},
    "search_refund_policy":    {"permission": "read",   "risk": "low",    "category": "query"},
    # ✏️ 操作类
    "create_ticket":           {"permission": "write",  "risk": "medium", "category": "action"},
    "cancel_order":            {"permission": "delete", "risk": "high",   "category": "action",
                                "high_risk_executor": lambda p:
                                    execute_cancel_order_confirmed(p.get("order_id", ""))},
}

# 需要用户确认的权限级别
PERMISSION_REQUIRES_CONFIRMATION = {"delete", "payment"}


# ═══════════════════════════════════════════════════════════
# 查询函数（agent.py 用 — 替代之前的手写函数）
# ═══════════════════════════════════════════════════════════

def get_meta(tool_name: str) -> dict:
    return TOOL_META.get(tool_name, {"permission": "read", "risk": "low", "category": "query"})


def get_permission(tool_name: str) -> str:
    return get_meta(tool_name)["permission"]


def get_risk_level(tool_name: str) -> str:
    return get_meta(tool_name)["risk"]


def is_high_risk(tool_name: str) -> bool:
    return get_meta(tool_name)["risk"] == "high"


def requires_confirmation(tool_name: str) -> bool:
    return get_meta(tool_name)["permission"] in PERMISSION_REQUIRES_CONFIRMATION


def get_high_risk_executor(tool_name: str):
    return TOOL_META.get(tool_name, {}).get("high_risk_executor")


# ═══════════════════════════════════════════════════════════
# Tool Routing（保留 — LangChain 没有内置等价功能）
# ═══════════════════════════════════════════════════════════

import re

ROUTING_PATTERNS = {
    "query":
        r"查|看|多少|到哪|在哪|物流|快递|进度|详情|信息|政策|规则|条件|"
        r"退.*条件|退.*政策|怎么退|多久|什么样|能不能|可以不|有没有|"
        r"如何|怎样|什么.*退|退.*什么|到账|时效|期限|流程",
    "action":
        r"取消|退[款货]|换[货]|投诉|工单|帮我.*创建|帮我.*申请|"
        r"我要退|我要换|我要取消|我要投诉|给我退|给我换|帮我退|帮我换|"
        r"我要.*退|我要.*换|我要.*取消|帮我.*退|帮我.*换|帮我.*取消",
}


def route_tools(user_message: str, verbose: bool = False) -> list:
    """意图分类 → 缩小发给 LLM 的工具集"""
    for category, pattern in ROUTING_PATTERNS.items():
        if re.search(pattern, user_message):
            narrowed = QUERY_TOOLS if category == "query" else ACTION_TOOLS
            if verbose:
                print(f"  🎯 Tool Routing: 意图={category} → "
                      f"发送 {len(narrowed)}/{len(ALL_TOOLS)} 个工具")
            return narrowed
    if verbose:
        print(f"  🎯 Tool Routing: 意图未识别 → 发送全部 {len(ALL_TOOLS)} 个工具")
    return ALL_TOOLS


# ═══════════════════════════════════════════════════════════
# 打印工具清单
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("📋 工具注册表（LangChain @tool）")
    print("=" * 60)

    for cat, label in [("query", "🔍 QUERY"), ("action", "✏️ ACTION")]:
        tools = [t for t in ALL_TOOLS if get_meta(t.name)["category"] == cat]
        print(f"\n{label} ({len(tools)} 个)：")
        for t in tools:
            m = get_meta(t.name)
            risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}[m["risk"]]
            perm_icon = {"read": "📖", "write": "✍️", "delete": "🗑️"}[m["permission"]]
            print(f"  {risk_icon} {perm_icon} {t.name}")
            print(f"     {t.description[:80]}...")

    print(f"\n📊 总计: {len(ALL_TOOLS)} 个工具")
    print(f"   LangChain @tool 装饰器自动生成 Function Calling Schema")

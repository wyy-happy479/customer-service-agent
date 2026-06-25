"""
工具注册表 — LLM "看见"的工具清单

📖 核心概念：
    工具注册表 = 工具定义（给 LLM 看的 JSON Schema）+ 工具执行函数（你的代码）。
    它把"LLM 的决策"和"真实世界的执行"连接起来。

🔍 底层原理：
    - tool_definitions：传给 OpenAI API 的 tools 参数
      LLM 根据每个工具的 name + description 做语义匹配，选最相关的
    - tool_executors：一个 dict，key 是工具名，value 是执行函数
      当 LLM 返回 tool_calls 时，你的代码根据 name 找到对应的执行函数

💡 为什么需要它：
    把"定义"和"执行"分开，方便管理和扩展。
    加一个新工具只需要两步：
    1. 在这里加一个 tool_definition
    2. 在 tool_executors 里写对应的执行函数
"""

from typing import Any, Callable
from tools.order_tools import execute_query_order, execute_query_orders_by_phone
from tools.logistics_tools import execute_track_logistics
from tools.refund_policy_tools import get_rag_engine
from tools.ticket_tools import execute_create_ticket
from tools.cancel_order_tools import execute_cancel_order, execute_cancel_order_confirmed


# ═══════════════════════════════════════════════════════════
# 工具定义（给 LLM 看的 — 标准的 OpenAI Function Calling 格式）
# ═══════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    # ── 1. 查询单个订单 ──
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "根据订单号查询单个订单的详细信息，包括商品名、金额、订单状态、下单时间。"
                           "当用户询问某个具体订单时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，格式为 ORD-XXXX（4位数字），如 ORD-0001"
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    # ── 2. 按手机号查订单 ──
    {
        "type": "function",
        "function": {
            "name": "query_orders_by_phone",
            "description": "根据手机号查询该用户的所有订单。当用户问'我的订单'但没有提供订单号时，"
                           "先用这个工具查出该用户的所有订单，再展示给用户。",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "11位中国大陆手机号，如 13800138000"
                    }
                },
                "required": ["phone"]
            }
        }
    },
    # ── 3. 查询物流 ──
    {
        "type": "function",
        "function": {
            "name": "track_logistics",
            "description": "根据订单号查询物流信息，包括快递公司、运单号、当前位置、完整物流时间线。"
                           "当用户问'我的快递到哪了'或'物流进度'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，格式为 ORD-XXXX"
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    # ── 4. 搜索退款政策（RAG） ──
    {
        "type": "function",
        "function": {
            "name": "search_refund_policy",
            "description": "搜索退款/退货/换货/售后政策。当用户询问退款规则、退货条件、换货流程、"
                           "退款时效等政策性问题时使用。这些是静态政策信息，不涉及具体订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户的政策问题，如'7天无理由退货的条件'、'退款多久到账'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    # ── 5. 创建售后工单 ──
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "为订单创建售后工单（退款/换货/投诉）。当用户明确要求退款、换货或投诉时使用。"
                           "注意：创建工单不代表自动退款，工单创建后由人工客服处理。",
            "parameters": {
                "type": "object",
                "properties": {
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
                "required": ["order_id", "ticket_type", "description"]
            }
        }
    },
    # ── 6. 取消订单（高风险） ──
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "取消指定订单。⚠️ 这是一个不可逆操作！执行前需要用户二次确认。"
                           "只有 pending（待发货）状态的订单可以取消。已发货的订单无法取消。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "要取消的订单号，格式为 ORD-XXXX"
                    }
                },
                "required": ["order_id"]
            }
        }
    },
]


# ═══════════════════════════════════════════════════════════
# 工具执行函数映射（你的代码 — 真正干活的）
# ═══════════════════════════════════════════════════════════

def _execute_search_refund_policy(params: dict) -> dict:
    """RAG 退款政策语义搜索（ChromaDB + Embedding）"""
    import json
    query = params.get("query", "")
    rag = get_rag_engine()
    result_str = rag.search(query)
    return json.loads(result_str)


# 工具名 → 执行函数 的映射表
TOOL_EXECUTORS: dict[str, Callable[[dict], dict]] = {
    "query_order": execute_query_order,
    "query_orders_by_phone": execute_query_orders_by_phone,
    "track_logistics": execute_track_logistics,
    "search_refund_policy": _execute_search_refund_policy,
    "create_ticket": execute_create_ticket,
    "cancel_order": execute_cancel_order,           # 第一阶段：返回 requires_confirmation
}


# ═══════════════════════════════════════════════════════════
# 高风险确认后的真正执行
# ═══════════════════════════════════════════════════════════

def execute_high_risk_confirmed(tool_name: str, params: dict) -> dict:
    """用户确认后执行高风险操作"""
    if tool_name == "cancel_order":
        order_id = params.get("order_id", "")
        return execute_cancel_order_confirmed(order_id)
    else:
        return {"success": False, "message": f"未知的高风险工具: {tool_name}"}


# ═══════════════════════════════════════════════════════════
# 工具名 → 风险等级 映射
# ═══════════════════════════════════════════════════════════

def get_risk_level(tool_name: str) -> str:
    """获取工具的风险等级"""
    from config import HIGH_RISK_TOOLS, MEDIUM_RISK_TOOLS
    if tool_name in HIGH_RISK_TOOLS:
        return "high"
    if tool_name in MEDIUM_RISK_TOOLS:
        return "medium"
    return "low"


def is_high_risk(tool_name: str) -> bool:
    """判断是否为高风险工具"""
    return get_risk_level(tool_name) == "high"

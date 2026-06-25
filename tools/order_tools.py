"""
订单查询工具

📖 核心概念：
    LLM 说要调 query_order → 你的代码去数据库查 → 返回结果给 LLM
    这一层就是 LLM 和真实数据之间的"翻译层"

🔍 底层原理：
    用 SQLite 做数据存储（database.py），这里只负责：
    1. 参数清洗（去空格、统一大写）
    2. 调用数据库查询
    3. 格式化返回结果（让 LLM 能"读懂"）

    注意：这里不做校验（validation.py 已经在前面校验过了），
    只做数据转换。
"""

from database import query_order, query_orders_by_phone
from validation import validate_params


def execute_query_order(params: dict) -> dict:
    """查询单个订单详情"""
    order_id = params.get("order_id", "").strip().upper()

    # 数据库查询
    order = query_order(order_id)

    if order is None:
        return {
            "success": False,
            "message": f"未找到订单 {order_id}。请确认订单号是否正确。"
        }

    # 格式化返回（去掉内部 ID，只保留用户关心的字段）
    return {
        "success": True,
        "order": {
            "order_id": order["order_id"],
            "customer_name": order["customer_name"],
            "product_name": order["product_name"],
            "amount": order["amount"],
            "status": order["status"],
            "created_at": order["created_at"],
        }
    }


def execute_query_orders_by_phone(params: dict) -> dict:
    """按手机号查询用户的所有订单"""
    phone = params.get("phone", "").strip()

    orders = query_orders_by_phone(phone)

    if not orders:
        return {
            "success": False,
            "message": f"未找到手机号 {phone} 关联的订单。请确认手机号是否正确。"
        }

    return {
        "success": True,
        "phone": phone,
        "count": len(orders),
        "orders": [
            {
                "order_id": o["order_id"],
                "product_name": o["product_name"],
                "amount": o["amount"],
                "status": o["status"],
                "created_at": o["created_at"],
            }
            for o in orders
        ]
    }

"""
物流查询工具

📖 核心概念：
    模拟调用外部物流 API。在真实业务中，这里应该是 HTTP 请求
    调顺丰/圆通的开放 API。这里用数据库模拟。

🔍 底层原理：
    物流数据存在 logistics 表里（database.py）。
    查物流时，你可能需要先查订单是否存在，再查物流——
    但 LLM 可能会连续调两个工具（先 query_order 确认订单存在，
    再 track_logistics 查物流），所以我们这里保持简单，
    直接查物流表即可。
"""

from database import query_logistics


def execute_track_logistics(params: dict) -> dict:
    """查询订单物流信息"""
    order_id = params.get("order_id", "").strip().upper()

    # 先查订单是否存在
    from database import query_order
    order = query_order(order_id)
    if order is None:
        return {
            "success": False,
            "message": f"未找到订单 {order_id}。请确认订单号是否正确。"
        }

    # 查物流
    logistics = query_logistics(order_id)
    if logistics is None:
        return {
            "success": False,
            "message": f"订单 {order_id}（{order['product_name']}）暂无物流信息。"
                       f"当前订单状态为：{order['status']}。"
        }

    # 格式化返回
    return {
        "success": True,
        "order_id": order_id,
        "product_name": order["product_name"],
        "carrier": logistics["carrier"],
        "tracking_no": logistics["tracking_no"],
        "current_location": logistics["current_location"],
        "status": logistics["status"],
        "timeline": logistics["timeline"],
    }

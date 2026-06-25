"""
工单创建工具

📖 核心概念：
    模拟售后工单系统——用户申请退款/换货/投诉时，创建一条工单记录。

🔍 底层原理：
    往 tickets 表 INSERT 一条记录。生成唯一工单号（TK-XXXX）。
    中等风险操作——不需要用户二次确认，但需要记录审计日志。
"""

from database import create_ticket


def execute_create_ticket(params: dict) -> dict:
    """创建售后工单"""
    order_id = params.get("order_id", "").strip().upper()
    ticket_type = params.get("ticket_type", "").strip()
    description = params.get("description", "").strip()

    # ticket_type 合法值检查
    valid_types = ["refund", "exchange", "complaint"]
    if ticket_type not in valid_types:
        return {
            "success": False,
            "message": f"工单类型「{ticket_type}」无效。"
                       f"可选类型：{'/'.join(valid_types)}"
        }

    return create_ticket(order_id, ticket_type, description)

"""
取消订单工具（高风险操作）

📖 核心概念：
    Human-in-the-Loop 的核心体现：AI 可以做决策，但不可逆的操作
    必须经过人类确认。这不是技术限制，而是设计原则。

🔍 底层原理：
    1. LLM 判断用户要取消订单 → 调 cancel_order
    2. 你的代码拦截 → 不执行，返回"需要确认"
    3. 用户输入"确认" → 你的代码才真正执行取消
    4. 用户输入其他 → 不执行，返回"已取消操作"

💡 为什么需要它：
    - 取消订单是不可逆的（取消了没法自动恢复）
    - LLM 可能误判用户意图（用户说"我想取消"不一定是真的要取消）
    - 合规要求：金融/电商领域的敏感操作必须有确认机制

    面试亮点：这叫 Human-in-the-Loop（人在回路），
    是 OpenAI/Anthropic 官方推荐的最佳实践。
"""

from database import cancel_order, query_order


def execute_cancel_order(params: dict) -> dict:
    """
    取消订单（第一阶段：仅做预检，不真正执行）

    这个函数只检查"能不能取消"，不真正取消。
    真正的取消操作在 human_in_the_loop.py 的 confirm 之后。
    """
    order_id = params.get("order_id", "").strip().upper()

    # 检查订单存在性
    order = query_order(order_id)
    if order is None:
        return {
            "success": False,
            "message": f"未找到订单 {order_id}。请确认订单号是否正确。"
        }

    # 返回一个"需要确认"的标记
    # Agent 循环检测到这个标记后，会走 Human-in-the-Loop 流程
    return {
        "success": False,  # 注意：这里返回 False 不是失败，而是"还没执行"
        "requires_confirmation": True,
        "order": {
            "order_id": order["order_id"],
            "product_name": order["product_name"],
            "amount": order["amount"],
            "status": order["status"],
        },
        "message": (
            f"⚠️  高风险操作确认\n\n"
            f"订单：{order['order_id']}\n"
            f"商品：{order['product_name']}\n"
            f"金额：¥{order['amount']}\n"
            f"当前状态：{order['status']}\n\n"
            f"取消订单后无法恢复，是否确认取消？\n"
            f"请输入「确认」继续，或输入其他内容放弃操作。"
        ),
    }


def execute_cancel_order_confirmed(order_id: str) -> dict:
    """
    用户确认后真正执行取消。
    这个函数只在 Human-in-the-Loop 确认后调用。
    """
    return cancel_order(order_id.strip().upper())

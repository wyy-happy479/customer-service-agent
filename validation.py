"""
参数校验模块（基于 Pydantic）

📖 核心概念：
    在工具真正执行之前，先检查参数是否合法。
    用 Pydantic 的 Field(pattern=...) 统一校验类型 + 格式，
    和项目 1 的结构化输出用的是同一个工具链。

🔍 底层原理：
    Pydantic 在实例化时自动校验每个字段：
    1. 类型检查 — str 不能传 int
    2. pattern 检查 — 用正则匹配字符串格式
    3. min_length 检查 — 字符串不能为空
    任一失败 → 抛出 ValidationError → 我们捕获并转成友好的错误提示

💡 为什么用 Pydantic 而不是手写正则：
    1. 声明式 — 规则写在一个地方，一眼看清所有字段约束
    2. 错误消息自动生成 — 不需要手动拼"正确格式如 ORD-0001，您提供的是..."
    3. 可组合 — 加一个新工具的校验只需要加一个 class，5 行代码
    4. 和项目 1 技术栈统一 — Schema 校验用同一套工具

    Pydantic vs 手写正则的对比：
    手写：pattern = "..."; if not re.match(pattern, x): return False, "错误消息"
    Pydantic：order_id: str = Field(pattern=r"...")
    后者把校验逻辑和错误消息内聚在一个地方，不容易出现"改了规则忘了改消息"的问题。

⚠️ 常见坑点：
    Pydantic v2 的 pattern 使用的是 Rust 的 regex 引擎，默认全文匹配。
    Pydantic v1 用的是 Python re.match()（默认前缀匹配）。
    所以如果项目用了 Pydantic v2，pattern="^ORD-\\d{4}$" 就是全字符串匹配。
"""

from pydantic import BaseModel, Field, field_validator, ValidationError


# ═══════════════════════════════════════════════════════════
# 每个工具一个 Pydantic Model — 字段即校验规则
# ═══════════════════════════════════════════════════════════

class QueryOrderParams(BaseModel):
    """查单条订单：订单号 ORD-XXXX"""
    order_id: str = Field(
        pattern=r"^ORD-\d{4}$",
        description="订单号，如 ORD-0001",
    )


class QueryOrdersByPhoneParams(BaseModel):
    """按手机号查订单：11 位中国大陆手机号"""
    phone: str = Field(
        min_length=11,
        description="11位手机号",
    )

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        """清理空格和横线，然后校验格式"""
        cleaned = v.strip().replace(" ", "").replace("-", "")
        import re
        if not re.match(r"^1[3-9]\d{9}$", cleaned):
            raise ValueError(f"手机号格式错误。应为11位中国大陆手机号，您提供的是：{v}")
        return cleaned


class TrackLogisticsParams(BaseModel):
    """查物流：订单号 ORD-XXXX"""
    order_id: str = Field(
        pattern=r"^ORD-\d{4}$",
        description="订单号，如 ORD-0001",
    )


class CancelOrderParams(BaseModel):
    """取消订单（高风险）：订单号 ORD-XXXX"""
    order_id: str = Field(
        pattern=r"^ORD-\d{4}$",
        description="订单号，如 ORD-0001",
    )


class CreateTicketParams(BaseModel):
    """创建售后工单：订单号 + 工单类型 + 问题描述"""
    order_id: str = Field(
        pattern=r"^ORD-\d{4}$",
        description="订单号，如 ORD-0001",
    )
    ticket_type: str = Field(
        min_length=1,
        description="工单类型：refund / exchange / complaint",
    )
    description: str = Field(
        min_length=1,
        description="问题描述",
    )


class SearchRefundPolicyParams(BaseModel):
    """搜索退款政策：查询关键词"""
    query: str = Field(
        min_length=1,
        description="搜索关键词",
    )


# ═══════════════════════════════════════════════════════════
# 工具名 → Pydantic Model 映射
# ═══════════════════════════════════════════════════════════

_PARAM_MODELS = {
    "query_order": QueryOrderParams,
    "query_orders_by_phone": QueryOrdersByPhoneParams,
    "track_logistics": TrackLogisticsParams,
    "cancel_order": CancelOrderParams,
    "create_ticket": CreateTicketParams,
    "search_refund_policy": SearchRefundPolicyParams,
}


# ═══════════════════════════════════════════════════════════
# 对外唯一的校验入口（和 agent.py 的调用方式完全兼容）
# ═══════════════════════════════════════════════════════════

def validate_params(tool_name: str, params: dict) -> tuple[bool, str]:
    """
    根据工具名校验参数。

    内部用 Pydantic Model 做声明式校验，
    对外保持 (bool, str) 的返回格式——agent.py 不用改。

    Returns:
        (是否通过, 错误信息——空字符串表示通过)
    """
    model_class = _PARAM_MODELS.get(tool_name)
    if model_class is None:
        # 未注册的工具不做校验（不应该发生，但兜底）
        return True, ""

    try:
        model_class(**params)
        return True, ""
    except ValidationError as e:
        # Pydantic 的错误信息自带字段名和约束描述，格式友好
        messages = []
        for error in e.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            messages.append(f"「{field}」{msg}")
        return False, "；".join(messages)


# ═══════════════════════════════════════════════════════════
# 快速自测
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("🧪 Pydantic 参数校验自测")
    print("=" * 50)

    # 合法输入
    print("\n✅ 合法输入：")
    tests_ok = [
        ("query_order", {"order_id": "ORD-0001"}),
        ("query_orders_by_phone", {"phone": "13800138000"}),
        ("track_logistics", {"order_id": "ORD-0003"}),
    ]
    for tool, params in tests_ok:
        ok, msg = validate_params(tool, params)
        icon = "✅" if ok else "❌"
        print(f"  {icon} {tool}({params}) → {msg or '通过'}")

    # 非法输入
    print("\n❌ 非法输入：")
    tests_bad = [
        ("query_order", {"order_id": "abc"}),
        ("query_order", {"order_id": ""}),
        ("query_orders_by_phone", {"phone": "12345"}),
        ("create_ticket", {"order_id": "ORD-0001", "ticket_type": "refund"}),
        ("create_ticket", {"order_id": "ORD-0001", "ticket_type": "refund", "description": ""}),
    ]
    for tool, params in tests_bad:
        ok, msg = validate_params(tool, params)
        icon = "✅" if ok else "❌"
        print(f"  {icon} {tool}({params}) → {msg}")

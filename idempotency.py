"""
Idempotency（幂等）模块

📖 核心概念：
    同一个操作执行一次和执行多次，结果相同 → 这就是幂等。
    在分布式系统中，"至少一次送达"语义下，幂等是防止重复扣款/重复下单的唯一防线。

🔍 底层原理：
    1. 每次写操作生成一个幂等键（idempotency key）
    2. 执行前检查这个 key 是否已经存在
    3. 存在 → 返回之前的结果（不重复执行）
    4. 不存在 → 执行 + 记录结果 + 存下幂等键

💡 为什么需要它：
    网络超时是最典型的场景——
    用户点了"创建工单"→ 你的代码执行了 → 但响应超时
    → 用户以为失败，再点一次 → 不应该创建两个工单

    面试话术：
    "我把'扣款'和'创建'这类操作做了幂等保护——每次执行前先检查幂等键，
     如果已存在就返回之前的结果，防止重复操作。这在分布式系统中是基本操作。"

⚠️ 常见坑点：
    1. 幂等键必须包含足够的信息来唯一标识一次操作
       → order_id + tool_name + timestamp 的前缀比纯随机 UUID 更好排查
    2. 幂等记录需要有时效性（不能永久保留所有记录）
       → 这里用内存 dict 做 demo，生产环境用 Redis + TTL
    3. 幂等不等于"不执行"——第一次必须执行，只是不执行第二次
"""

import hashlib
import json
import time
from typing import Any


# 内存存储（demo 用，生产环境改 Redis）
_idempotency_store: dict[str, dict[str, Any]] = {}

# 幂等记录保留时间（秒）
IDEMPOTENCY_TTL = 3600  # 1 小时


def make_idempotency_key(tool_name: str, params: dict) -> str:
    """
    生成幂等键。

    格式：{tool_name}:{params_hash}
    比如：create_ticket:abc123def456

    为什么用 hash 而不是原始参数？
    - 缩短 key 长度
    - 避免 key 中包含敏感信息（手机号等）
    """
    params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
    return f"{tool_name}:{params_hash}"


def check_and_set(key: str, ttl: int = IDEMPOTENCY_TTL) -> dict[str, Any] | None:
    """
    检查幂等键是否已存在。

    Returns:
        None → 第一次执行，继续
        dict → 已存在，返回之前缓存的结果（不重复执行）

    数据结构：{"result": ..., "timestamp": ...}
    """
    if key in _idempotency_store:
        entry = _idempotency_store[key]
        # 检查是否过期
        if time.time() - entry["timestamp"] < ttl:
            return entry["result"]
        else:
            # 过期了，删除旧记录
            del _idempotency_store[key]
    return None


def set_result(key: str, result: dict[str, Any]):
    """存储幂等结果"""
    _idempotency_store[key] = {
        "result": result,
        "timestamp": time.time(),
    }


def is_idempotent_tool(tool_name: str) -> bool:
    """判断工具是否需要幂等保护"""
    # 写操作都需要幂等保护，只读操作不需要
    from tool_registry import get_permission
    perm = get_permission(tool_name)
    return perm in ("write", "delete", "payment")


def cleanup_expired(ttl: int = IDEMPOTENCY_TTL):
    """清理过期的幂等记录（定期调用）"""
    now = time.time()
    expired = [k for k, v in _idempotency_store.items() if now - v["timestamp"] > ttl]
    for k in expired:
        del _idempotency_store[k]
    return len(expired)


if __name__ == "__main__":
    # 快速测试
    key1 = make_idempotency_key("create_ticket", {
        "order_id": "ORD-0001",
        "ticket_type": "refund",
        "description": "坏了"
    })
    print(f"幂等键: {key1}")

    # 同样参数 → 同样的 key
    key2 = make_idempotency_key("create_ticket", {
        "ticket_type": "refund",
        "order_id": "ORD-0001",
        "description": "坏了"
    })
    print(f"相同参数: {key2}")
    print(f"key 相同? {'✅' if key1 == key2 else '❌'}")

    # 不同参数 → 不同 key
    key3 = make_idempotency_key("create_ticket", {
        "order_id": "ORD-0002",
        "ticket_type": "refund",
        "description": "坏了"
    })
    print(f"不同参数: {key3}")
    print(f"key 不同? {'✅' if key1 != key3 else '❌'}")

    # 幂等检查
    print(f"\n首次检查 '{key1}': {check_and_set(key1)}")   # None → 第一次
    set_result(key1, {"success": True, "ticket_id": "TK-0099"})
    print(f"二次检查 '{key1}': {check_and_set(key1)}")   # 有结果 → 幂等命中

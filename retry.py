"""
重试策略 — 基于 tenacity 库

📖 核心概念：
    tenacity 是 Python 最成熟的纯重试库，Star 6k+。
    不需要手写 while 循环 + sleep + 指数计算。

🔍 之前 vs 现在：

    之前（手写 120 行）：
        def retry_with_backoff(func, max_retries=3, ...):
            for attempt in range(max_retries + 1):
                try: return func()
                except Exception as e:
                    classify_error(e)  # 手写分类
                    if non_retryable: raise
                    sleep(backoff * 2**attempt)  # 手写退避

    现在（tenacity 3 行）：
        @retry(
            retry=retry_if_exception_type((TimeoutError, ConnectionError)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, max=10),
        )
        def my_func(): ...

💡 为什么生产环境用 tenacity：
    1. 不要重复造轮子 — 重试是公认的通用模式，tenacity 已经做到极致
    2. 组合式 API — retry/stop/wait/before/after 五个维度独立配置
    3. 面试加分 — "我用 tenacity 做重试，retry_if + wait_exponential"
"""

import random
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_log,
    after_log,
    RetryError,
)

from enum import Enum

import logging
logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"


# ═══════════════════════════════════════════════════════════
# 错误分类（tenacity 用 retry_if_exception 做白名单）
# ═══════════════════════════════════════════════════════════

RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    ConnectionAbortedError,
    OSError,
)

RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable(exception: Exception) -> bool:
    """白名单策略：只有明确列出的才重试"""
    # 1. 异常类型在可重试名单里
    if isinstance(exception, RETRYABLE_EXCEPTIONS):
        return True

    # 2. HTTP 状态码在可重试名单里
    if hasattr(exception, "status_code"):
        status = exception.status_code  # type: ignore
        if status in RETRYABLE_HTTP_CODES:
            return True

    # 3. OpenAI API 的特定错误类型
    if hasattr(exception, "body") and isinstance(exception.body, dict):  # type: ignore
        error_type = exception.body.get("type", "")  # type: ignore
        return error_type in ("server_error", "rate_limit_error")

    return False


def classify_error(exception: Exception) -> ErrorCategory:
    """错误分类（对外保留，和之前接口兼容）"""
    if _is_retryable(exception):
        return ErrorCategory.RETRYABLE
    return ErrorCategory.NON_RETRYABLE


# ═══════════════════════════════════════════════════════════
# 与 Agent 的集成接口（tenacity 包装）
# ═══════════════════════════════════════════════════════════

def execute_with_retry(
    executor,
    tool_name: str = "",
    max_retries: int = 3,
    base_delay: float = 1.0,
    verbose: bool = False,
):
    """
    工具执行 + tenacity 自动重试。

    tenacity 做的事：
    - retry_if_exception(_is_retryable): 只重试可重试错误
    - stop_after_attempt(3): 最多 3 次
    - wait_exponential(multiplier=1, max=10): 指数退避 1s→2s→4s，上限 10s
    """
    retry_decorator = retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(max_retries + 1),  # +1 因为第一次不算 retry
        wait=wait_exponential(multiplier=base_delay, max=10.0),
        reraise=True,
    )

    decorated_func = retry_decorator(executor)

    try:
        return decorated_func()
    except RetryError as e:
        # tenacity 把所有重试都失败后包成 RetryError
        original = e.__cause__ or e
        if verbose:
            print(f"  💀 {tool_name} 已重试 {max_retries} 次，放弃")
        raise original
    except Exception as e:
        # 不可重试错误 → 直接上抛
        if verbose:
            print(f"  ⛔ {tool_name} 不可重试错误: {e.__class__.__name__}")
        raise


# ═══════════════════════════════════════════════════════════
# 快速自测
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("🧪 tenacity 重试策略测试")
    print("=" * 50)

    # 测试1：可重试错误
    print("\n1. 可重试错误（模拟网络超时）：")
    call_count = [0]

    def flaky():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("网络超时")
        return "成功！"

    result = execute_with_retry(flaky, tool_name="test", verbose=True)
    print(f"   结果: {result}（共调用 {call_count[0]} 次）")

    # 测试2：不可重试错误
    print("\n2. 不可重试错误（参数错误）：")
    try:
        execute_with_retry(lambda: int("abc"), tool_name="test", verbose=True)
    except ValueError:
        print("   立即失败，没有重试 ✅")

    # 测试3：错误分类
    print("\n3. 错误分类：")
    for err_cls in [ConnectionError, TimeoutError, ValueError, KeyError]:
        e = err_cls("test")
        cat = classify_error(e).value
        icon = "✅" if (err_cls in RETRYABLE_EXCEPTIONS and cat == "retryable") or \
                       (err_cls not in RETRYABLE_EXCEPTIONS and cat == "non_retryable") else "❌"
        print(f"  {icon} {err_cls.__name__} → {cat}")

"""
Retry Policy（重试策略）模块

📖 核心概念：
    不是所有错误都适合重试。关键在于区分"这次失败了，再来一次可能成功"
    和"这次失败了，再来一百次也是失败"。

🔍 底层原理：
    错误分两类：
    1. 可重试（Retryable）：网络超时、限流、服务暂时不可用
       → 等一等再试，大概率成功
    2. 不可重试（Non-retryable）：参数错误、余额不足、权限不够
       → 重试没意义，应该立即返回错误

    重试策略用指数退避（Exponential Backoff）：
    第1次失败 → 等 1s → 第2次失败 → 等 2s → 第3次失败 → 等 4s → 放弃

💡 为什么需要它：
    没有重试 → 网络抖动就报错，用户体验差
    盲目重试 → 扣款操作重试 3 次 = 可能扣 3 次钱！（所以要和幂等配合）

    面试话术：
    "我写了一个可重试错误的白名单——网络超时、限流、503 等临时故障走指数退避重试；
     参数错误、权限不足等确定性错误立刻返回，不做无意义重试。
     同时写操作重试前先查幂等键，防止重复执行。"

⚠️ 常见坑点：
    1. 重试必须区分错误类型 → 否则参数错误也会重试 3 次，浪费资源和时间
    2. 写操作重试必须带幂等键 → 否则扣款可能重复
    3. 不要对所有错误都重试 → 503（服务不可用）重试，400（参数错误）不重试
"""

import time
import random
from typing import Callable, Any
from enum import Enum


class ErrorCategory(str, Enum):
    """错误类别"""
    RETRYABLE = "retryable"            # 可重试：临时故障
    NON_RETRYABLE = "non_retryable"   # 不可重试：确定性错误


# ═══════════════════════════════════════════════════════════
# 可重试的错误白名单（不是黑名单——只有名单里的才重试）
# ═══════════════════════════════════════════════════════════

# HTTP 状态码 → 是否可重试
RETRYABLE_HTTP_CODES = {
    408: True,   # Request Timeout
    429: True,   # Rate Limit
    500: True,   # Internal Server Error
    502: True,   # Bad Gateway
    503: True,   # Service Unavailable
    504: True,   # Gateway Timeout
}

# 异常类型 → 错误类别
RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    ConnectionAbortedError,
    OSError,              # 网络层错误
)

# 不可重试的异常（即使它看起来像网络错误）
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,           # 参数错误
    TypeError,            # 类型错误
    KeyError,             # 键不存在
    FileNotFoundError,    # 文件不存在
)


def classify_error(error: Exception) -> ErrorCategory:
    """
    给错误分类：可重试 vs 不可重试。

    思路：
    - 网络类异常 → 可重试（临时故障）
    - 逻辑/参数类异常 → 不可重试（重试也没用）
    - HTTP 状态码 4xx → 不可重试（客户端错误）
    - HTTP 状态码 5xx → 可重试（服务端临时故障）
    """
    # 1. 检查异常类型
    if isinstance(error, NON_RETRYABLE_EXCEPTIONS):
        return ErrorCategory.NON_RETRYABLE

    if isinstance(error, RETRYABLE_EXCEPTIONS):
        return ErrorCategory.RETRYABLE

    # 2. 尝试从异常消息中提取 HTTP 状态码
    error_str = str(error)
    if hasattr(error, "status_code"):
        status = error.status_code  # type: ignore
        if RETRYABLE_HTTP_CODES.get(status, False):
            return ErrorCategory.RETRYABLE
        if 400 <= status < 500 and status != 429:
            return ErrorCategory.NON_RETRYABLE

    # 3. 如果有 body（OpenAI API 的标准错误格式）
    if hasattr(error, "body") and isinstance(error.body, dict):  # type: ignore
        error_body = error.body  # type: ignore
        if error_body.get("type") == "invalid_request_error":
            return ErrorCategory.NON_RETRYABLE
        if error_body.get("type") == "insufficient_quota":
            return ErrorCategory.NON_RETRYABLE

    # 4. 兜底：未知错误 → 不重试（保守策略）
    return ErrorCategory.NON_RETRYABLE


def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    verbose: bool = False,
    tool_name: str = "",
) -> Any:
    """
    带指数退避的重试执行器。

    Args:
        func: 要执行的函数（无参数）
        max_retries: 最大重试次数
        base_delay: 基础等待时间（秒），每次翻倍
        max_delay: 最大等待时间（秒），不超此值
        verbose: 是否打印重试信息
        tool_name: 工具名（用于日志前缀）

    Returns:
        函数返回值

    Raises:
        最后一次重试的异常（如果全部失败）

    时间线示例（base=1s, max_retries=3）：
    尝试1 → 失败 → 等 1.0s + jitter
    尝试2 → 失败 → 等 2.0s + jitter
    尝试3 → 失败 → 等 4.0s + jitter
    尝试4（最后）→ 成功或抛异常
    """
    last_error = None

    for attempt in range(max_retries + 1):  # 总共执行 1 + max_retries 次
        try:
            return func()
        except Exception as e:
            last_error = e
            category = classify_error(e)

            if category == ErrorCategory.NON_RETRYABLE:
                if verbose:
                    print(f"  ⛔ {tool_name} 不可重试错误: {e.__class__.__name__}")
                raise  # 立即退出，不重试

            if attempt == max_retries:
                if verbose:
                    print(f"  💀 {tool_name} 已重试 {max_retries} 次，放弃")
                raise  # 用完了所有重试次数

            # 指数退避 + jitter（避免多客户端同时重试产生风暴）
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.3)  # ±30% 随机抖动
            sleep_time = delay + jitter

            if verbose:
                print(f"  🔄 {tool_name} {e.__class__.__name__}，"
                      f"第 {attempt + 1}/{max_retries} 次重试，"
                      f"等待 {sleep_time:.1f}s")

            time.sleep(sleep_time)

    # 理论上不会到这，但兜底
    if last_error:
        raise last_error


# ═══════════════════════════════════════════════════════════
# 与 Agent 的集成接口
# ═══════════════════════════════════════════════════════════

def execute_with_retry(
    executor: Callable[[], Any],
    tool_name: str,
    verbose: bool = False,
) -> dict:
    """
    工具执行 + 自动重试（agent.py 直接调这个）。

    做的事：
    1. 把 executor 包上重试逻辑
    2. 不可重试错误 → 立即返回错误信息（不重试）
    3. 可重试错误 → 指数退避重试，最多 3 次
    4. 全部失败 → 返回友好错误消息
    """
    try:
        return retry_with_backoff(
            executor,
            max_retries=3,
            verbose=verbose,
            tool_name=tool_name,
        )
    except Exception as e:
        category = classify_error(e)
        return {
            "success": False,
            "message": f"工具 '{tool_name}' 执行失败: {e.__class__.__name__}: {str(e)[:200]}",
            "error_category": category.value,
        }


if __name__ == "__main__":
    print("=" * 50)
    print("🧪 重试策略测试")
    print("=" * 50)

    # 测试1：可重试错误（模拟网络超时）
    print("\n1. 可重试错误（模拟网络超时）：")
    call_count = [0]

    def flaky_func():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("网络超时")
        return "成功！"

    result = retry_with_backoff(flaky_func, max_retries=3, verbose=True, tool_name="query_order")
    print(f"   结果: {result}（共调用 {call_count[0]} 次）")

    # 测试2：不可重试错误（参数错误）
    print("\n2. 不可重试错误（参数错误）：")
    try:
        retry_with_backoff(lambda: int("abc"), max_retries=3, verbose=True, tool_name="parser")
    except ValueError:
        print("   立即失败，没有重试 ✅")

    # 测试3：错误分类
    print("\n3. 错误分类测试：")
    errors = {
        ConnectionError("连接超时"): "retryable",
        TimeoutError(): "retryable",
        ValueError("参数错误"): "non_retryable",
        KeyError("键不存在"): "non_retryable",
    }
    for err, expected in errors.items():
        actual = classify_error(err).value
        icon = "✅" if actual == expected else "❌"
        print(f"  {icon} {err.__class__.__name__} → {actual}")

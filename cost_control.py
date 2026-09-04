"""
cost_control.py — 可靠性层（第 ④ 步）

研报 Agent 的成本与可靠性控制:
  - TokenBudget:         token 累计计数器（全流水线共用一把尺）
  - call_api_with_retry: API 调用包装（失败重试 + 指数退避）

config 里的旋钮在这里变成执行逻辑:
  MAX_TOTAL_TOKENS → TokenBudget 的限额
  MAX_RETRIES      → call_api_with_retry 的重试次数
"""
import sys
import time

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════
# ① TokenBudget —— 全流水线的"共享计数器"
# ═══════════════════════════════════════════════════════════

class TokenBudget:
    """累计 token 消耗，超限后由调用方降级（降级逻辑在 pipeline）。"""

    def __init__(self, limit: int | None = None):
        self.limit = limit if limit is not None else config.MAX_TOTAL_TOKENS
        self.used = 0

    def add(self, n: int) -> int:
        """记一笔消耗，返回当前累计值。"""
        self.used += n
        return self.used

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    @property
    def exceeded(self) -> bool:
        return self.used >= self.limit

    def status(self) -> str:
        return f"token: {self.used:,} / {self.limit:,} ({self.used / self.limit:.0%})"


# ═══════════════════════════════════════════════════════════
# ② call_api_with_retry —— 重试分级 + 指数退避
# ═══════════════════════════════════════════════════════════

# 重试分级: 只有"暂时性错误"值得重试
#  - 超时/连接失败/限流 → 等会儿可能就好 → 重试
#  - 401 key 错/400 参数错 → 重试一万次也没用 → 立即抛
try:
    from openai import APITimeoutError, APIConnectionError, RateLimitError
    RETRYABLE_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError,
                        ConnectionError, TimeoutError)
except ImportError:   # 没装 openai 时退化为内置异常
    RETRYABLE_ERRORS = (ConnectionError, TimeoutError)


def call_api_with_retry(func, *args, max_retries: int | None = None, **kwargs):
    """调用 func(*args, **kwargs)，失败自动重试。

    重试分级:
      - RETRYABLE_ERRORS 内的暂时性错误 → 指数退避重试
        （间隔: 1s → 2s → 4s ...，2 的 attempt 次方）
      - 其他异常（401/400 等确定性错误）→ 不重试，立即抛出

    重试耗尽仍失败 → 抛出最后一个异常，交给上层决定怎么办。
    """
    retries = max_retries if max_retries is not None else config.MAX_RETRIES
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except RETRYABLE_ERRORS as e:
            if attempt >= retries:
                raise                      # 暂时性错误重试耗尽 → 抛给上层
            wait = 2 ** attempt            # 1, 2, 4 ... 秒
            print(f"⚠️ 暂时性错误: {str(e)[:50]} → {wait}s 后重试 ({attempt + 1}/{retries})")
            time.sleep(wait)
        # 确定性错误（401/400/ValueError 等）→ 不重试，直接抛


if __name__ == "__main__":
    # 自检: python cost_control.py
    print("═" * 50)
    print("测试 1: TokenBudget")
    b = TokenBudget(limit=1000)
    b.add(300)
    b.add(650)
    print(f"  两笔消耗后: {b.status()}")
    print(f"  剩余: {b.remaining} | 是否超限: {b.exceeded}")
    b.add(100)
    print(f"  再加一笔后: {b.status()} | 是否超限: {b.exceeded}")

    print("\n测试 2: 重试成功（模拟前两次失败、第三次成功）")
    calls = {"n": 0}

    def fake_api():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("网络波动")
        return "成功!"

    result = call_api_with_retry(fake_api, max_retries=3)
    print(f"  结果: {result}（共调用 {calls['n']} 次）")

    print("\n测试 3: 暂时性错误全部失败 → 重试耗尽后抛出")
    def always_fail():
        raise TimeoutError("永远超时")
    try:
        call_api_with_retry(always_fail, max_retries=2)
    except TimeoutError as e:
        print(f"  重试耗尽后正确抛出: {e}")

    print("\n测试 4: 确定性错误 → 不重试，立即抛出")
    n = {"calls": 0}
    def wrong_key():
        n["calls"] += 1
        raise ValueError("API key 无效 (401)")   # 确定性错误：重试无意义
    try:
        call_api_with_retry(wrong_key, max_retries=3)
    except ValueError as e:
        print(f"  立即抛出: {e}（只调用了 {n['calls']} 次，没浪费重试）")
    print("═" * 50)
    print("✅ 可靠性层自检完成")

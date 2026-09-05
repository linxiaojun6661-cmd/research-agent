"""
auth.py — 鉴权 + 限流（P0 补全 ①）

鉴权: 花钱的 POST /research 需要 Bearer Token（API_TOKEN 环境变量）
      —— config.API_TOKEN 为空时自动不启用，本地开发零负担
限流: 滑动窗口，每 IP 独立计数；/research 限额更严（每次调用都花 API 钱）

用法:
  启用鉴权:  set API_TOKEN=你的token 后启动服务
  调用示例:  Authorization: Bearer 你的token
"""
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

import config

# ═══════════════════════════════════════════════════════════
# ① 鉴权 —— Bearer Token 校验
# ═══════════════════════════════════════════════════════════

def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI 依赖: 校验 Authorization: Bearer <token> 头。"""
    if not config.API_TOKEN:
        return                             # 未配置 = 不启用（开发模式）
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少认证 token")
    if authorization.removeprefix("Bearer ") != config.API_TOKEN:
        raise HTTPException(401, "认证失败")


# ═══════════════════════════════════════════════════════════
# ② 限流 —— 滑动窗口
# ═══════════════════════════════════════════════════════════

class RateLimiter:
    """每 key（IP）维护最近 60 秒的请求时间戳队列。"""

    def __init__(self, window: float = 60.0):
        self.window = window
        self._hits: dict = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()                    # 扔掉窗口外的旧请求
        if len(q) >= limit:
            return False                   # 窗口内已满 → 拒绝
        q.append(now)
        return True


limiter = RateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """全局限流中间件: /research 用严格限额，其余接口宽松。

    ⚠️ 坑: 中间件里 raise HTTPException 会炸成 500（BaseHTTPMiddleware 不接），
    必须直接 return JSONResponse 才是干净的 429。
    """
    ip = request.client.host if request.client else "unknown"
    is_research = request.url.path == "/research"
    limit = config.RESEARCH_RATE_LIMIT if is_research else config.RATE_LIMIT_PER_MINUTE
    # ⚠️ 按 IP+接口类别 分桶: 否则 /health 的请求会吃掉 /research 的配额
    bucket = f"{ip}:{'research' if is_research else 'default'}"
    if not limiter.allow(bucket, limit):
        return JSONResponse(status_code=429,
                            content={"detail": "请求太频繁，请稍后再试"})
    return await call_next(request)


if __name__ == "__main__":
    # 自检: python auth.py —— 纯离线单元测试
    print("═" * 50)
    print("测试 1: 限流器基本行为（limit=2）")
    rl = RateLimiter()
    print(f"  第1次: {'✅ 放行' if rl.allow('ip1', 2) else '❌'}")
    print(f"  第2次: {'✅ 放行' if rl.allow('ip1', 2) else '❌'}")
    print(f"  第3次: {'✅ 正确拒绝' if not rl.allow('ip1', 2) else '❌ 没拦住'}")
    print(f"  另一IP不受影响: {'✅' if rl.allow('ip2', 2) else '❌'}")

    print("\n测试 2: 窗口滑动（等 1.1 秒后旧记录过期）")
    rl2 = RateLimiter(window=1.0)
    rl2.allow('ip', 1)
    print(f"  窗口内第2次: {'✅ 正确拒绝' if not rl2.allow('ip', 1) else '❌'}")
    time.sleep(1.1)
    print(f"  1.1 秒后再来: {'✅ 正确放行' if rl2.allow('ip', 1) else '❌'}")

    print("\n测试 3: 鉴权（未配置 token = 开发模式）")
    import asyncio
    try:
        require_auth(None)
        print("  ✅ 未配置 API_TOKEN 时直接放行")
    except HTTPException:
        print("  ❌ 应该放行")

    print("\n测试 4: 鉴权（配置 token 后拒绝无凭证）")
    config.API_TOKEN = "test-secret"
    try:
        require_auth(None)
        print("  ❌ 应该拒绝")
    except HTTPException as e:
        print(f"  ✅ 正确拒绝: HTTP {e.status_code}")
    print("  （配置了 token 后，Bearer 头缺失/错误都会被 401 拦下）")
    print("═" * 50)

"""
trace_log.py — 可观测层（第 ⑤ 步）

全链路 JSONL 日志器: 每次运行生成一个 trace 文件，记录
API 调用 / 工具调用 / 预算检查 / 运行结果等所有关键事件。

为什么是 JSONL:
  - 一行一个 JSON 对象，append 追加写入 → 崩溃也不丢已写日志
  - 逐行可解析 → 你的 analyze_trace.py 稍加改造就能分析它
    （和 Claude Code 会话的 JSONL trace 是同一个世界）
"""
import json
import sys
import time
from datetime import datetime

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class TraceLogger:
    """一次运行 = 一个 TraceLogger = 一个 trace 文件。"""

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = config.TRACE_DIR / f"run_{self.run_id}.jsonl"
        self.start = time.time()
        self._write("run_start", {"run_id": self.run_id})

    # ── 内部: 统一写入格式 ──
    def _write(self, event: str, detail: dict):
        entry = {
            "ts": datetime.now().isoformat(),          # 墙上时间
            "elapsed": round(time.time() - self.start, 2),  # 距开跑秒数（分析延迟用）
            "event": event,
            **detail,                                   # 事件自有字段展开进来
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── 对外: 各类事件的记录方法 ──
    def log(self, event: str, **detail):
        """通用记录: trace.log("tool_call", name="web_search")"""
        self._write(event, detail)

    def log_api(self, model: str, tokens_in: int, tokens_out: int, duration: float):
        """记录一次 LLM API 调用（成本核算的数据来源）。
        duration = 本次调用耗时 —— 注意不叫 elapsed，避免和
        外层统一字段 elapsed（距开跑秒数）同名冲突。"""
        self.log("api_call", model=model,
                 tokens_in=tokens_in, tokens_out=tokens_out, duration=duration)

    def log_tool(self, name: str, args: dict, result_preview: str):
        """记录一次工具调用，结果只留预览（防日志爆炸）。"""
        self.log("tool_call", name=name, args=args,
                 result_preview=result_preview[:100])

    def log_budget(self, budget):
        """记录预算状态（超没超限一目了然）。"""
        self.log("budget_check", used=budget.used, limit=budget.limit,
                 exceeded=budget.exceeded)

    def finish(self, status: str, **detail):
        """运行结束标记，返回 trace 文件路径。"""
        self.log("run_end", status=status, **detail)
        return str(self.path)


if __name__ == "__main__":
    # 自检: python trace_log.py —— 写几条假日志再读回来验证
    print("═" * 50)
    trace = TraceLogger(run_id="selftest")
    trace.log_api("deepseek-chat", tokens_in=1200, tokens_out=300, duration=2.3)
    trace.log_tool("web_search", {"query": "大模型"}, "找到: Python - 维基百科...")
    trace.log("safety_check", allowed=True, reason="域名在白名单")
    path = trace.finish("ok", report="outputs/test.md")

    print(f"✅ trace 文件: {path}")
    print("\n文件内容（每行一个 JSON）:")
    for line in open(path, encoding="utf-8"):
        print(" ", line.strip())

    # 验证: 逐行 json.loads 都能解析 = 机器可分析
    parsed = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    print(f"\n✅ 逐行解析成功: {len(parsed)} 条事件，可直接交给 analyze_trace.py")
    print("═" * 50)

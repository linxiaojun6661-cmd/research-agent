"""
eval_runner.py — Golden 主题集回归（第 ⑪ 步）

固定主题集 + 全自动跑管线 + judge 验收 + 成本断言。
每次改完代码跑一遍，防止"新功能改坏老功能"。

用法:
  python eval_runner.py           # 只跑第 1 个主题（省钱模式）
  python eval_runner.py --full    # 跑全部主题（约 3 倍 API 费用）
"""
import json
import sys
from datetime import datetime

import config
import cost_control
import pipeline
from eval_report import judge_report, score_report
from main import make_safe_filename
from trace_log import TraceLogger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 历史成绩单: 每次回归的记录，用于跨版本对比（分数退化立刻可见）
HISTORY_FILE = config.OUTPUT_DIR / "eval_history.json"


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {}


def previous_score(topic: str) -> int | None:
    runs = load_history().get(topic, [])
    return runs[-1]["score"] if runs else None


def record_score(topic: str, total: int):
    h = load_history()
    h.setdefault(topic, []).append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "score": total,
    })
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=1),
                            encoding="utf-8")

# 固定主题集: 覆盖面广、体量小，控制回归成本
GOLDEN_TOPICS = [
    "什么是 RAG",
    "MCP 协议是什么",
    "Python 是什么语言",
]
PER_TOPIC_BUDGET = 60_000      # 单主题预算: 回归成本可控


def count_tokens(trace_path: str) -> int:
    """从 trace 统计实际 token 消耗（成本断言的数据来源）。"""
    total = 0
    for line in open(trace_path, encoding="utf-8"):
        e = json.loads(line)
        if e["event"] == "api_call":
            total += e.get("tokens_in", 0) + e.get("tokens_out", 0)
    return total


def run_topic(topic: str, idx: int) -> tuple[bool, dict]:
    """跑一个主题: 管线 → 成本统计 → judge 验收。返回 (通过?, 结果)。"""
    print(f"▶ [{idx}] {topic} ...", flush=True)
    budget = cost_control.TokenBudget(limit=PER_TOPIC_BUDGET)
    trace = TraceLogger()          # 时间戳命名，天然不重复
    report = pipeline.run_pipeline(topic, auto_yes=True,
                                   budget=budget, trace=trace)
    r = {"topic": topic, "trace": trace.path.name}

    if report is None:
        r["status"] = "❌ 未生成报告"
        return False, r

    tokens = count_tokens(trace.path)
    verdict = judge_report(report)
    ok_judge, fail, total = score_report(verdict)

    # 历史对比: 与上次同主题成绩做差（负分 = 退化，立刻报警）
    prev = previous_score(topic)
    record_score(topic, total)
    delta = f"{total - prev:+d}" if prev is not None else "首测"

    out = config.OUTPUT_DIR / f"{make_safe_filename('golden_' + topic)}.md"
    out.write_text(report, encoding="utf-8")

    r.update({
        "chars": f"{len(report):,}字",
        "judge": f"{'✅' if ok_judge else '❌'} {total}分({delta})",
        "cost": f"{tokens:,}/{PER_TOPIC_BUDGET:,}",
        "report": out.name,
    })
    return ok_judge and tokens <= PER_TOPIC_BUDGET, r


if __name__ == "__main__":
    topics = GOLDEN_TOPICS if "--full" in sys.argv else GOLDEN_TOPICS[:1]

    results = []
    for i, topic in enumerate(topics, 1):
        ok, r = run_topic(topic, i)
        results.append((ok, r))

    print("\n" + "═" * 60)
    print("📊 Golden 回归成绩单")
    print("═" * 60)
    print(f"  {'主题':<16} {'报告':<10} {'judge':<10} {'成本':<18} 结论")
    print("─" * 60)
    for ok, r in results:
        mark = "✅" if ok else "❌"
        print(f"  {r['topic']:<16} {r.get('chars','-'):<10} "
              f"{r.get('judge','-'):<10} {r.get('cost','-'):<18} {mark}")
    print("═" * 60)
    passed = sum(1 for ok, _ in results if ok)
    print(f"总评: {passed}/{len(results)} 通过")
    sys.exit(0 if passed == len(results) else 1)

"""
main.py — CLI 入口（第 ⑦ 步）

用法:
  python main.py "2026 年国产大模型现状"     # 完整流程（搜索计划会问 y/N）
  python main.py "主题" --yes                # 跳过人工确认
  python main.py "主题" --budget 50000       # 覆盖 token 预算上限
  python main.py --list-traces               # 看最近的 trace 文件
"""
import argparse
import re
import sys
from datetime import datetime

import config
import cost_control
import pipeline
from trace_log import TraceLogger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_safe_filename(topic: str) -> str:
    """把主题变成合法文件名: 去掉 Windows 非法字符 + 截断 + 时间戳防覆盖。"""
    illegal = r'[\\/:*?"<>|\s]+'         # Windows 非法字符 + 空白符
    cleaned = re.sub(illegal, "_", topic).strip("_")[:40]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cleaned or 'report'}_{stamp}"


def main():
    parser = argparse.ArgumentParser(
        description="研报 Agent: 输入主题，输出带引用的调研报告")
    parser.add_argument("topic", nargs="?", help="调研主题（不传则列出 trace）")
    parser.add_argument("--yes", action="store_true",
                        help="跳过搜索计划的人工确认")
    parser.add_argument("--budget", type=int, default=None,
                        help=f"覆盖 token 预算上限（默认 {config.MAX_TOTAL_TOKENS:,}）")
    parser.add_argument("--list-traces", action="store_true",
                        help="列出最近的 trace 文件")
    args = parser.parse_args()

    if args.list_traces or not args.topic:
        # 过滤掉自检文件: run_selftest.jsonl 按字典序会排在时间戳之后，干扰排序
        files = sorted(p for p in config.TRACE_DIR.glob("run_*.jsonl")
                       if "selftest" not in p.name)
        print(f"最近 {min(5, len(files))} 个 trace:")
        for p in files[-5:]:
            print(f"  {p.name}")
        return

    print("═" * 60)
    print("📊 研报 Agent 启动")
    print(f"   主题: {args.topic}")
    print(f"   预算: {args.budget if args.budget else config.MAX_TOTAL_TOKENS:,} tokens")
    print("═" * 60)

    # --budget 覆盖: 传自定义 TokenBudget；不传则用 pipeline 的默认
    budget = (cost_control.TokenBudget(limit=args.budget)
              if args.budget else None)

    # ⚠️ 自己持有 trace: 直接知道日志路径，而不是事后"猜最新文件"
    trace = TraceLogger()
    report = pipeline.run_pipeline(args.topic, auto_yes=args.yes,
                                   budget=budget, trace=trace)

    if report is None:
        print("\n❌ 未生成报告（主题被拦截或计划被拒绝），详情见 trace 日志")
        print(f"   trace 日志: {trace.path.name}")
        return

    out = config.OUTPUT_DIR / f"{make_safe_filename(args.topic)}.md"
    out.write_text(report, encoding="utf-8")   # 报告自带标题（writer 职责），不重复加

    print("\n" + "═" * 60)
    print(f"✅ 报告已保存: {out}")
    print(f"   共 {len(report)} 字符")
    print(f"   trace 日志: {trace.path.name}")
    print("═" * 60)


if __name__ == "__main__":
    main()

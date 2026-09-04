"""
eval_report.py — 报告质量评测（第 ⑩ 步）—— LLM-as-judge

用另一个 LLM 当"裁判"，按统一标准给报告打分:
  citation  引用可溯源（关键论断有 [n] 标注 + 参考来源有 URL）
  structure 结构完整（摘要/正文/结论/参考来源）
  language  语言正确（中文报告）

用法:
  python eval_report.py                  # 评测 outputs/ 里最新的报告
  python eval_report.py <报告文件.md>    # 评测指定报告
"""
import os
import sys

import config
import cost_control
import pipeline

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JUDGE_SYSTEM = (
    "你是报告质量审查员。审查以下调研报告，只输出一个 JSON 对象，"
    "不要输出任何其他文字:\n"
    '{"citation": true/false, "structure": true/false, "language": true/false,'
    ' "issues": ["问题描述"]}\n'
    "判定标准:\n"
    "1. citation: 报告关键论断有 [n] 引用标注，且文末参考来源列出对应 URL。"
    "整篇完全没有任何标注 → false\n"
    "2. structure: 包含 摘要/正文/结论/参考来源 类结构。缺任一主要章节 → false\n"
    "3. language: 正文语言为中文。整篇英文 → false\n"
    "issues 数组写具体问题（没有则空数组）。"
    "严禁复述或粘贴报告内容，只输出 JSON 本身。"
)


def judge_report(report: str) -> dict:
    """LLM-as-judge: 一次 API 调用，返回质量裁决 JSON。"""
    resp = cost_control.call_api_with_retry(
        pipeline.CLIENT.chat.completions.create,
        model=config.MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": report[:8000]},   # 截断: 裁判看样本即可
        ],
        timeout=config.API_TIMEOUT,
    )
    text = resp.choices[0].message.content or ""
    return pipeline.safe_json_load(text)


def score_report(verdict: dict) -> tuple[bool, str]:
    """把裁决转成 (是否通过, 失败原因)。三项全过才算过。"""
    if not verdict.get("citation"):
        return False, "引用不可溯源"
    if not verdict.get("structure"):
        return False, "结构不完整"
    if not verdict.get("language"):
        return False, "语言错误"
    return True, ""


def print_report_card(path: str, verdict: dict):
    """打印成绩单。"""
    ok, fail_reason = score_report(verdict)
    print("═" * 50)
    print(f"📋 报告质量成绩单: {os.path.basename(path)}")
    print("─" * 50)
    print(f"  引用可溯源: {'✅' if verdict.get('citation') else '❌'}")
    print(f"  结构完整:   {'✅' if verdict.get('structure') else '❌'}")
    print(f"  语言中文:   {'✅' if verdict.get('language') else '❌'}")
    print(f"  总评: {'✅ 通过' if ok else '❌ ' + fail_reason}")
    for issue in verdict.get("issues", []):
        print(f"    · {issue}")
    print("═" * 50)
    return ok


def latest_report() -> str:
    """outputs/ 里最新修改的报告文件。"""
    reports = list(config.OUTPUT_DIR.glob("*.md"))
    if not reports:
        return ""
    return str(max(reports, key=os.path.getmtime))


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else latest_report()
    if not path:
        print("❌ outputs/ 里没有报告可评测。先跑 python main.py \"主题\" 生成一份。")
        sys.exit(1)

    report = open(path, encoding="utf-8").read()
    print(f"正在评测: {path}（{len(report)} 字符）")
    verdict = judge_report(report)
    ok = print_report_card(path, verdict)
    sys.exit(0 if ok else 1)

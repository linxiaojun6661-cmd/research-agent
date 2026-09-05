"""
eval_report.py — 报告质量评测（第 ⑩ 步 + P0-④ 量化强化）—— LLM-as-judge

与 pipeline 里 reviewer 的分工（重叠问题的最终答案）:
  reviewer = 门卫: 二元 pass/issues，管"要不要再改一轮"（生产内，每篇必跑）
  judge    = 打分员: 0-100 量化，管"值多少分、能不能验收"（生产外，评测时跑）

三维打分 + 加权总分:
  citation  引用可溯源（权重 0.5 —— 研报立身之本）
  structure 结构完整（权重 0.3）
  language  语言中文（权重 0.2）
  通过线: 总分 ≥ 70 且单项 ≥ 60

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
    '{"citation": 0-100, "structure": 0-100, "language": 0-100,'
    ' "issues": ["问题描述"]}\n'
    "打分标准（0-100 整数，按下面档位给分）:\n"
    "1. citation 引用可溯源: 关键论断都有 [n] 标注、参考来源有 URL 且来源权威"
    " =90+；有标注但部分来源权威性弱 =70-85；部分论断无标注 =40-60；"
    "整篇无任何标注 =0-20\n"
    "2. structure 结构完整: 摘要/正文/结论/参考来源齐全且逻辑清晰 =90+；"
    "缺小节或条理一般 =60-85；缺主要章节 =0-50\n"
    "3. language 中文表达: 通顺专业 =90+；中文为主偶有英文 =50-80；"
    "整篇英文 =0-20\n"
    "issues 数组写具体问题（没有则空数组）。"
    "严禁复述或粘贴报告内容，只输出 JSON 本身。"
)

# 加权: 引用是研报立身之本，权重最高
WEIGHTS = {"citation": 0.5, "structure": 0.3, "language": 0.2}
PASS_TOTAL = 70      # 总分通过线
PASS_MIN_DIM = 60    # 单项最低线（一项太差就不能靠别的拉分）


def judge_report(report: str) -> dict:
    """LLM-as-judge: 一次 API 调用，返回三维打分 JSON。"""
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


def score_report(verdict: dict) -> tuple[bool, str, int]:
    """把裁决转成 (是否通过, 失败原因, 总分)。"""
    scores = {k: float(verdict.get(k, 0)) for k in WEIGHTS}
    total = round(sum(scores[k] * w for k, w in WEIGHTS.items()))
    dim_fails = [k for k, v in scores.items() if v < PASS_MIN_DIM]
    if total >= PASS_TOTAL and not dim_fails:
        return True, "", total
    if dim_fails:
        return False, f"单项不合格: {','.join(dim_fails)}", total
    return False, f"总分不足 {PASS_TOTAL}", total


def grade(total: int) -> str:
    if total >= 85:
        return "优秀"
    if total >= 70:
        return "合格"
    return "不合格"


def print_report_card(path: str, verdict: dict):
    """打印成绩单（三维分数 + 加权总分 + 等级）。"""
    ok, fail_reason, total = score_report(verdict)
    print("═" * 50)
    print(f"📋 报告质量成绩单: {os.path.basename(path)}")
    print("─" * 50)
    print(f"  引用可溯源: {verdict.get('citation', 0):>3} 分（权重 0.5）")
    print(f"  结构完整:   {verdict.get('structure', 0):>3} 分（权重 0.3）")
    print(f"  语言中文:   {verdict.get('language', 0):>3} 分（权重 0.2）")
    print(f"  ─────────────────────────")
    print(f"  加权总分: {total} / 100  [{grade(total)}]  "
          f"{'✅ 通过' if ok else '❌ ' + fail_reason}")
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

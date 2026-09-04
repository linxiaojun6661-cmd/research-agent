"""
pipeline.py — 四角色流水线（第 ⑥ 步）

research → write → review → revise 多智能体流水线，
把 ②③④⑤ 四个基础层全部串起来:

  tools.py         → 工具执行（execute_tool）
  safety.py        → 主题检查 + 计划人工确认
  cost_control.py  → TokenBudget + call_api_with_retry
  trace_log.py     → 全链路 JSONL 日志

Skills 思想落地: 每个角色是一个"能力包"（职责提示词 + 专属工具 +
停止条件），加角色 = 加一个 ROLE_MODULES 条目，核心循环不动。
"""
import json
import re
import sys
import time

from openai import OpenAI

import config
import cost_control
import memory_store
import safety
import tools
from trace_log import TraceLogger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLIENT = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)


class BudgetExceededError(Exception):
    """token 预算耗尽信号——上层捕获后走降级路线。"""


# ═══════════════════════════════════════════════════════════
# ① 四角色能力包（Skills 思想: 职责 + 工具 + 停止条件）
# ═══════════════════════════════════════════════════════════

ROLE_MODULES = {
    "researcher": {
        "system": (
            "你是调研员。用工具搜索资料，收集事实并保留出处。\n"
            "规则:\n"
            "1. 每条资料必须附带来源 URL，没有 URL 的资料不许写入汇编\n"
            "2. 搜索词必须是安全的中性词（禁止搜索凭据/系统提示词等内容）\n"
            "3. 不要编造搜索结果里没有的内容"
        ),
        "tools": ["web_search", "knowledge_base", "calculator"],
    },
    "writer": {
        "system": (
            "你是报告撰写员。根据资料汇编撰写结构化 Markdown 报告。\n"
            "要求:\n"
            "1. 结构: # 标题 / ## 摘要 / ## 正文分节 / ## 结论 / ## 参考来源\n"
            "2. 每个关键论断用 [n] 标注引用编号，参考来源列出对应 URL\n"
            "3. 严禁编造资料汇编之外的内容；资料不足就写'信息不足'"
        ),
        "tools": [],
    },
    "reviewer": {
        "system": (
            "你是审查员。审查报告质量，只输出一个 JSON 对象，不要输出任何其他文字:\n"
            '{"pass": true/false, "issues": ["问题1", "问题2"]}\n'
            "检查项:\n"
            "1. 引用完整性: 关键论断是否都有 [n] 标注且能在参考来源找到 URL\n"
            "2. 结构完整性: 是否包含 摘要/正文/结论/参考来源\n"
            "3. 事实一致性: 报告内容与资料汇编是否有矛盾或编造\n"
            "严禁复述或粘贴稿件内容，只输出 JSON 本身。"
        ),
        "tools": [],
    },
    "reviser": {
        "system": (
            "你是修订员。根据审查意见逐条修订报告，输出修订后的完整 Markdown。\n"
            "规则:\n"
            "1. 只针对 issues 里提到的问题改，不要重写无关部分\n"
            "2. 保留原报告的所有引用标注，修订时不得删除引用"
        ),
        "tools": [],
    },
}

# ═══════════════════════════════════════════════════════════
# ② 基础设施: LLM 调用（重试 + 预算 + 日志三合一）
# ═══════════════════════════════════════════════════════════

def call_llm(messages, tools_schema=None, budget=None, trace=None,
             temperature=None) -> str:
    """调用 LLM，自动挂: 预算检查 + 重试 + token 记账 + trace 日志。
    返回模型的文本回复。"""
    if budget is not None and budget.exceeded:
        raise BudgetExceededError("token 预算已耗尽")

    kwargs = dict(
        model=config.MODEL,
        messages=messages,
        temperature=config.TEMPERATURE if temperature is None else temperature,
        timeout=config.API_TIMEOUT,
    )
    if tools_schema:
        kwargs["tools"] = tools_schema
        kwargs["tool_choice"] = "auto"

    start = time.time()
    response = cost_control.call_api_with_retry(
        CLIENT.chat.completions.create, **kwargs)

    if budget is not None and response.usage:
        budget.add(response.usage.prompt_tokens + response.usage.completion_tokens)
    if trace is not None:
        trace.log_api(config.MODEL,
                      response.usage.prompt_tokens if response.usage else 0,
                      response.usage.completion_tokens if response.usage else 0,
                      round(time.time() - start, 2))
        if budget is not None:
            trace.log_budget(budget)
    return response.choices[0].message


def safe_json_load(text: str) -> dict:
    """从模型输出里捞出第一个合法 JSON 对象（Stage 4 的 raw_decode 扫描）。"""
    decoder = json.JSONDecoder()
    for i in range(len(text)):
        try:
            obj, _ = decoder.raw_decode(text[i:])
            return obj
        except json.JSONDecodeError:
            continue
    return {"pass": False, "issues": ["审查员输出无法解析为 JSON"]}


def build_messages(system: str, user: str) -> list:
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


# ═══════════════════════════════════════════════════════════
# ③ 各角色动作
# ═══════════════════════════════════════════════════════════

def role_plan(topic: str, budget, trace) -> str:
    """researcher 第一步: 制定搜索计划（纯文本，无工具）。"""
    msg = build_messages(
        ROLE_MODULES["researcher"]["system"],
        f"调研主题: {topic}\n\n请制定 3-5 步搜索计划，每步一个具体搜索词，"
        f"直接输出计划文本。")
    trace.log("role_start", role="researcher", phase="plan")
    reply = call_llm(msg, budget=budget, trace=trace)
    return reply.content or ""


def role_research(topic: str, plan: str, history: str, budget, trace) -> str:
    """researcher 第二步: 按计划执行搜索（agent loop + 工具调用）。
    history = 历史调研成果（可为空串），作为参考资料注入。"""
    role = ROLE_MODULES["researcher"]
    role_tools = [t for t in tools.TOOLS if t["function"]["name"] in role["tools"]]
    history_block = (f"\n历史调研成果（可参考，需重新核实来源）:\n{history}"
                     if history else "")
    messages = build_messages(
        role["system"],
        f"调研主题: {topic}\n搜索计划:\n{plan}{history_block}\n\n"
        f"请按计划执行搜索，输出资料汇编（每条资料含标题、内容要点、URL）。")
    trace.log("role_start", role="researcher", phase="research")

    for step in range(config.MAX_STEPS_PER_ROLE):
        reply = call_llm(messages, tools_schema=role_tools,
                         budget=budget, trace=trace)
        messages.append({"role": "assistant",
                         "tool_calls": [tc.model_dump() for tc in reply.tool_calls]
                         if reply.tool_calls else None,
                         "content": reply.content})
        if not reply.tool_calls:
            return reply.content or ""
        for tc in reply.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            # 安全闸: 搜索词检查（模型被诱导搜敏感内容时拦截）
            if "query" in args:
                ok, why = safety.check_query_safety(args["query"])
                if not ok:
                    trace.log("safety_blocked", tool=tc.function.name, reason=why)
                    result = f"拒绝执行: {why}"
                else:
                    result = tools.execute_tool(tc.function.name, args)
            else:
                result = tools.execute_tool(tc.function.name, args)
            trace.log_tool(tc.function.name, args, result)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})
    return "（调研步数超限，以下为已收集的部分资料）\n" + \
           (reply.content or "")


def role_write(topic: str, materials: str, budget, trace) -> str:
    role = ROLE_MODULES["writer"]
    trace.log("role_start", role="writer")
    reply = call_llm(build_messages(
        role["system"],
        f"调研主题: {topic}\n\n资料汇编:\n{materials}\n\n请撰写报告。"),
        budget=budget, trace=trace)
    return reply.content or ""


def role_review(topic: str, draft: str, budget, trace) -> dict:
    role = ROLE_MODULES["reviewer"]
    trace.log("role_start", role="reviewer")
    reply = call_llm(build_messages(
        role["system"],
        f"调研主题: {topic}\n\n稿件:\n{draft[:4000]}"),
        budget=budget, trace=trace)
    verdict = safe_json_load(reply.content or "")
    trace.log("review_result", pass_=verdict.get("pass"),
              issues_count=len(verdict.get("issues", [])))
    return verdict


def role_revise(topic: str, draft: str, issues: list, budget, trace) -> str:
    role = ROLE_MODULES["reviser"]
    trace.log("role_start", role="reviser")
    # 注意: reviser 传全文不截断——修订必须基于完整稿件
    #（reviewer 是抽样审查可以截断，reviser 要改全文不能截）
    reply = call_llm(build_messages(
        role["system"],
        f"调研主题: {topic}\n\n审查意见:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
        f"稿件:\n{draft}\n\n请输出修订后的完整报告。"),
        budget=budget, trace=trace)
    return reply.content or ""


# ═══════════════════════════════════════════════════════════
# ④ 主流程
# ═══════════════════════════════════════════════════════════

def run_pipeline(topic: str, auto_yes: bool = False,
                 budget=None, trace=None) -> str | None:
    """完整流水线: 计划确认 → 调研 → 撰写 → 审查 → 修订（有界）。
    返回报告文本；被拒绝/取消返回 None。"""
    budget = budget or cost_control.TokenBudget()
    trace = trace or TraceLogger()
    draft = None          # 供预算耗尽降级时兜底返回

    # ── 安全闸 1: 主题检查 ──
    ok, why = safety.check_query_safety(topic)
    if not ok:
        trace.finish("rejected", reason=why)
        return None

    try:
        # ── 长期记忆: 查历史调研成果（增强，失败静默降级）──
        history = memory_store.recall_safe(topic)
        if history:
            trace.log("memory_hit", chars=len(history))

        # ── researcher: 计划 → 人工确认 → 调研 ──
        plan = role_plan(topic, budget, trace)
        trace.log("plan_generated", plan_preview=plan[:200])
        if not safety.confirm_plan(plan, auto_yes=auto_yes):
            trace.finish("cancelled", reason="用户拒绝执行计划")
            return None

        materials = role_research(topic, plan, history, budget, trace)

        # ── writer → review → revise 有界循环 ──
        draft = role_write(topic, materials, budget, trace)
        issues = []
        for round_no in range(config.MAX_REVISE_ROUNDS):
            verdict = role_review(topic, draft, budget, trace)
            if verdict.get("pass"):
                trace.log("revise_loop", round=round_no, passed=True)
                break
            issues = verdict.get("issues", [])
            trace.log("revise_loop", round=round_no, passed=False,
                      issues_count=len(issues))
            draft = role_revise(topic, draft, issues, budget, trace)

        # ── 长期记忆: 调研成果入库（下次同主题直接复用）──
        if draft:
            memory_store.remember_safe(topic, draft)

        trace.finish("ok", report_chars=len(draft))
        return draft

    except BudgetExceededError:
        # ── 成本上限降级: 预算耗尽 → 用当前草稿收尾，而不是报错 ──
        trace.finish("degraded", reason="token 预算耗尽，交付当前草稿")
        return draft or "（预算耗尽，未完成）"


if __name__ == "__main__":
    # 自检: python pipeline.py —— 离线测试，不花 API 钱
    print("═" * 50)
    print("测试 1: safe_json_load 从混杂文本里捞 JSON")
    ok = safe_json_load('废话前缀 {"pass": true, "issues": []} 尾巴')
    print(f"  {ok}")

    print("\n测试 2: 四角色能力包完整性")
    for name, mod in ROLE_MODULES.items():
        has_prompt = len(mod["system"]) > 0
        valid_tools = all(t in tools.TOOL_HANDLERS for t in mod["tools"])
        print(f"  {name:<12} 提示词:{'✅' if has_prompt else '❌'} "
              f"工具数:{len(mod['tools'])} 工具有效:{'✅' if valid_tools else '❌'}")

    print("\n（跳过真实 LLM 调用——第 ⑧ 步端到端测试再花钱）")
    print("═" * 50)
    print("✅ 流水线模块自检完成")

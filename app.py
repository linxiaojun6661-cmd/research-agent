"""
app.py — FastAPI 服务（后端补全）

把研报 Agent 包装成 HTTP 服务:
  POST /research         提交主题 → 完整流水线 → 报告 + judge 评分 + trace
  GET  /reports          列出历史报告
  GET  /reports/{name}   取单份报告
  GET  /health           健康检查

运行: uvicorn app:app --port 8123
"""
import sys
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

import async_tasks
import auth
import config
import pipeline
from eval_report import judge_report
from main import make_safe_filename
from trace_log import TraceLogger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = FastAPI(title="研报 Agent", description="多智能体调研报告流水线 API")

# P0 安全: 全局限流中间件（/research 限额更严）
app.middleware("http")(auth.rate_limit_middleware)


# ═══════════════════════════════════════════════════════════
# 请求/响应模型（Pydantic: 自动校验入参，自动生成 API 文档）
# ═══════════════════════════════════════════════════════════

class ResearchRequest(BaseModel):
    topic: str
    auto_yes: bool = True       # API 场景默认自动批准（调用方已获授权）
    judge: bool = True          # 是否附带 judge 质量评分


class ResearchResponse(BaseModel):
    success: bool
    report: str | None = None
    judge_verdict: dict | None = None
    trace_file: str | None = None
    message: str | None = None


class TaskSubmitResponse(BaseModel):
    task_id: str
    status_url: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str                 # pending / running / done / failed
    report: str | None = None
    judge_verdict: dict | None = None
    trace_file: str | None = None
    error: str | None = None


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


def _run_research_job(topic: str, auto_yes: bool, judge: bool) -> dict:
    """后台任务体: 跑流水线 + judge + 落盘。返回结果字典。"""
    # ⚠️ 自己持有 trace（猜不如持有——glob 会有 selftest 字典序陷阱）
    trace = TraceLogger()
    report = pipeline.run_pipeline(topic, auto_yes=auto_yes, trace=trace)
    if report is None:
        return {"report": None, "message": "主题被拦截或计划被拒绝",
                "trace_file": trace.path.name, "judge_verdict": None}

    verdict = judge_report(report) if judge else None
    out = config.OUTPUT_DIR / f"{make_safe_filename(topic)}.md"
    out.write_text(report, encoding="utf-8")
    return {"report": report, "judge_verdict": verdict,
            "trace_file": trace.path.name, "message": None}


@app.post("/research", response_model=TaskSubmitResponse,
          status_code=202)
def research(req: ResearchRequest, _: None = Depends(auth.require_auth)):
    """提交调研任务: 秒回 task_id（HTTP 202），后台异步执行。"""
    task_id = async_tasks.submit_task(
        _run_research_job, req.topic, req.auto_yes, req.judge)
    return TaskSubmitResponse(task_id=task_id,
                              status_url=f"/research/{task_id}")


@app.get("/research/{task_id}", response_model=TaskStatusResponse)
def research_status(task_id: str):
    """轮询任务状态: pending → running → done/failed。"""
    t = async_tasks.get_task(task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    result = t["result"] or {}
    return TaskStatusResponse(
        task_id=task_id, status=t["status"],
        report=result.get("report"),
        judge_verdict=result.get("judge_verdict"),
        trace_file=result.get("trace_file"),
        error=t["error"])


@app.get("/reports")
def list_reports():
    """列出所有已生成报告。"""
    return {"reports": [p.name for p in sorted(config.OUTPUT_DIR.glob("*.md"))]}


@app.get("/reports/{name}")
def get_report(name: str):
    p = config.OUTPUT_DIR / name
    if not p.exists():
        raise HTTPException(404, "报告不存在")
    return {"name": name, "content": p.read_text(encoding="utf-8")}

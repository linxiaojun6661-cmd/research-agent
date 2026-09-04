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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
import pipeline
from eval_report import judge_report
from main import make_safe_filename
from trace_log import TraceLogger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = FastAPI(title="研报 Agent", description="多智能体调研报告流水线 API")


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


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/research", response_model=ResearchResponse)
def research(req: ResearchRequest):
    """提交主题，同步跑完整流水线（约 1-3 分钟）。"""
    # ⚠️ 自己持有 trace（猜不如持有——glob 会有 selftest 字典序陷阱）
    trace = TraceLogger()
    report = pipeline.run_pipeline(req.topic, auto_yes=req.auto_yes,
                                   trace=trace)
    if report is None:
        return ResearchResponse(success=False,
                                message="主题被拦截或计划被拒绝")

    verdict = judge_report(report) if req.judge else None

    out = config.OUTPUT_DIR / f"{make_safe_filename(req.topic)}.md"
    out.write_text(report, encoding="utf-8")

    return ResearchResponse(success=True, report=report,
                            judge_verdict=verdict,
                            trace_file=trace.path.name)


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

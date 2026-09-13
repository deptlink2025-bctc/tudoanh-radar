"""Màn hình máy tính (localhost:8100): hàng đợi quý + duyệt từng báo cáo.

Chạy: start-review.bat  (hoặc  venv\\Scripts\\python -m uvicorn ingest.review_server:app --port 8100)
Giao diện tĩnh ở ingest/review_static/, gọi các API dưới đây.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from common import quarters
from common.config import TZ

from . import brokers as brokers_cfg
from . import export, pipeline
from . import slice as pdfslice
from .db import init_db, session
from .models import STEP_INDEX, Broker, Holding, Report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("review")

STATIC = Path(__file__).parent / "review_static"
app = FastAPI(title="TuDoanh Radar — duyệt BCTC")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = session()
    n = brokers_cfg.seed(db)
    if n:
        log.info("Đã thêm %d công ty mặc định", n)
    db.close()


# ---------------------------------------------------------------- trang

@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------------------------------------------------------- hàng đợi

def _rep_dict(rep: Report) -> dict:
    checks = json.loads(rep.checks_json or "{}")
    n_rows = sum(1 for h in rep.holdings if not h.deleted)
    n_flag = sum(1 for h in rep.holdings if not h.deleted and h.flags)
    n_missing = sum(1 for h in rep.holdings if not h.deleted and h.is_listed and (h.cost_value is None or h.quantity is None))
    return {
        "id": rep.id, "broker": rep.broker, "quarter": rep.quarter, "stmt_type": rep.stmt_type,
        "status": rep.status, "step": STEP_INDEX.get(rep.status, 0), "running": pipeline.is_running(rep.id),
        "stuck_step": rep.stuck_step, "stuck_reason": rep.stuck_reason,
        "source_url": rep.source_url, "page_count": rep.page_count, "note_pages": rep.note_pages,
        "model_used": rep.model_used, "extracted_at": rep.extracted_at.isoformat() if rep.extracted_at else None,
        "approved_at": rep.approved_at.isoformat() if rep.approved_at else None,
        "n_rows": n_rows, "n_flag": n_flag, "n_missing": n_missing,
        "checks": checks.get("checks") or [], "notes": checks.get("notes") or "",
        "usage": checks.get("usage"), "finfo": json.loads(rep.finfo_json or "{}"),
    }


@app.get("/api/queue")
def queue(quarter: str = ""):
    db = session()
    q = quarter or quarters.latest_reported()
    brokers = db.query(Broker).order_by(Broker.symbol).all()
    reps = {r.broker: r for r in db.query(Report).filter_by(quarter=q).all()}
    rows = []
    for b in brokers:
        r = reps.get(b.symbol)
        rows.append({"broker": b.symbol, "name": b.name, "enabled": b.enabled, "report": _rep_dict(r) if r else None})
    all_q = sorted({r.quarter for r in db.query(Report).all()} | {q}, reverse=True)
    db.close()
    return {"quarter": q, "label": quarters.label(q), "quarters": all_q, "rows": rows}


class StartBody(BaseModel):
    quarter: str


@app.post("/api/start")
def start(body: StartBody):
    quarters.parse(body.quarter)
    ids = pipeline.start_quarter(body.quarter)
    return {"started": len(ids)}


class ResumeBody(BaseModel):
    pdf_url: str = ""
    pages: str = ""      # "42,43,44"


@app.post("/api/report/{rid}/resume")
def resume(rid: int, body: ResumeBody):
    db = session()
    rep = db.get(Report, rid)
    if rep is None:
        raise HTTPException(404)
    pages = [int(p) for p in body.pages.replace(" ", "").split(",") if p.isdigit()] or None
    if body.pdf_url:
        rep.source_url, rep.pdf_path, rep.note_pages = body.pdf_url, "", ""
        db.commit()
        from_step = "fetching"
    elif pages:
        from_step = "locating"
    else:
        from_step = rep.stuck_step or "fetching"
    db.close()
    pipeline.run_async(rid, from_step=from_step, pdf_url=body.pdf_url, pages=pages)
    return {"ok": True, "from": from_step}


@app.post("/api/report/{rid}/rerun/{step}")
def rerun(rid: int, step: str):
    if step not in pipeline.STEPS:
        raise HTTPException(400, "bước không hợp lệ")
    pipeline.run_async(rid, from_step=step)
    return {"ok": True}


# ---------------------------------------------------------------- duyệt

def _h_dict(h: Holding) -> dict:
    return {
        "id": h.id, "asset_class": h.asset_class, "ticker": h.ticker, "raw_label": h.raw_label,
        "is_listed": h.is_listed, "quantity": h.quantity, "quantity_source": h.quantity_source,
        "cost_value": h.cost_value, "cost_source": h.cost_source, "fair_value": h.fair_value,
        "fair_source": h.fair_source, "confidence": h.confidence, "flags": h.flags, "deleted": h.deleted,
    }


@app.get("/api/report/{rid}")
def report(rid: int):
    db = session()
    rep = db.get(Report, rid)
    if rep is None:
        raise HTTPException(404)
    d = _rep_dict(rep)
    d["holdings"] = [_h_dict(h) for h in rep.holdings]
    d["closes"] = json.loads(rep.checks_json or "{}").get("closes") or {}
    db.close()
    return d


@app.get("/api/report/{rid}/page/{page_no}")
def page_image(rid: int, page_no: int):
    db = session()
    rep = db.get(Report, rid)
    db.close()
    if rep is None or not rep.pdf_path:
        raise HTTPException(404)
    if page_no < 1 or page_no > rep.page_count:
        raise HTTPException(404)
    p = pdfslice.cache_page_png(rep.pdf_path, rep.broker, rep.quarter, page_no, dpi=110)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


class HoldingBody(BaseModel):
    asset_class: str | None = None
    ticker: str | None = None
    quantity: float | None = None
    cost_value: float | None = None
    fair_value: float | None = None
    is_listed: bool | None = None
    deleted: bool | None = None


@app.patch("/api/holding/{hid}")
def patch_holding(hid: int, body: HoldingBody):
    """Sửa tay một ô → trường *_source thành 'manual'."""
    db = session()
    h = db.get(Holding, hid)
    if h is None:
        raise HTTPException(404)
    if body.asset_class is not None:
        h.asset_class = body.asset_class
    if body.ticker is not None:
        h.ticker = body.ticker.strip().upper()
    if body.quantity is not None and body.quantity != h.quantity:
        h.quantity, h.quantity_source = body.quantity, "manual"
    if body.cost_value is not None and body.cost_value != h.cost_value:
        h.cost_value, h.cost_source = body.cost_value, "manual"
    if body.fair_value is not None and body.fair_value != h.fair_value:
        h.fair_value, h.fair_source = body.fair_value, "manual"
    if body.is_listed is not None:
        h.is_listed = body.is_listed
    if body.deleted is not None:
        h.deleted = body.deleted
    db.commit()
    out = _h_dict(h)
    db.close()
    return out


class NewHoldingBody(BaseModel):
    asset_class: str = "FVTPL"
    ticker: str
    quantity: float | None = None
    cost_value: float | None = None
    fair_value: float | None = None


@app.post("/api/report/{rid}/holding")
def add_holding(rid: int, body: NewHoldingBody):
    db = session()
    rep = db.get(Report, rid)
    if rep is None:
        raise HTTPException(404)
    h = Holding(report_id=rid, asset_class=body.asset_class, ticker=body.ticker.strip().upper(),
                raw_label="(nhập tay)", is_listed=True, quantity=body.quantity, quantity_source="manual",
                cost_value=body.cost_value, cost_source="manual", fair_value=body.fair_value, fair_source="manual",
                confidence=1.0)
    db.add(h)
    db.commit()
    out = _h_dict(h)
    db.close()
    return out


@app.post("/api/report/{rid}/approve")
def approve(rid: int):
    db = session()
    rep = db.get(Report, rid)
    if rep is None:
        raise HTTPException(404)
    if rep.status not in ("review", "approved"):
        raise HTTPException(400, "Báo cáo chưa qua bước đối chiếu")
    rep.status = "approved"
    rep.approved_at = datetime.now(TZ).replace(tzinfo=None, microsecond=0)
    db.commit()
    db.close()
    export.write()
    return {"ok": True, "push": export.push()}


@app.post("/api/report/{rid}/reopen")
def reopen(rid: int):
    db = session()
    rep = db.get(Report, rid)
    if rep is None:
        raise HTTPException(404)
    rep.status = "review"
    db.commit()
    db.close()
    return {"ok": True}


class ManualReportBody(BaseModel):
    broker: str
    quarter: str


@app.post("/api/report/manual")
def manual_report(body: ManualReportBody):
    """Tạo báo cáo rỗng ở trạng thái review để nhập tay hoàn toàn (không bóc PDF)."""
    db = session()
    rep = db.query(Report).filter_by(broker=body.broker.upper(), quarter=body.quarter, stmt_type="rieng").one_or_none()
    if rep is None:
        rep = Report(broker=body.broker.upper(), quarter=body.quarter, status="review", model_used="manual")
        db.add(rep)
        db.commit()
    rid = rep.id
    db.close()
    return {"id": rid}


# ---------------------------------------------------------------- công ty

@app.get("/api/brokers")
def list_brokers():
    db = session()
    out = [{"symbol": b.symbol, "name": b.name, "floor": b.floor, "enabled": b.enabled, "ir_url": b.ir_url}
           for b in db.query(Broker).order_by(Broker.symbol).all()]
    db.close()
    return out


@app.get("/api/universe")
def universe():
    db = session()
    try:
        uni = brokers_cfg.refresh_universe(db)
    finally:
        db.close()
    return uni


class BrokerBody(BaseModel):
    symbol: str
    name: str = ""
    floor: str = ""
    ir_url: str = ""
    enabled: bool = True


@app.post("/api/brokers")
def upsert_broker(body: BrokerBody):
    db = session()
    b = db.get(Broker, body.symbol.upper())
    if b is None:
        b = Broker(symbol=body.symbol.upper())
        db.add(b)
    b.name, b.floor, b.enabled = body.name or b.name, body.floor or b.floor, body.enabled
    if body.ir_url:
        b.ir_url = body.ir_url
    db.commit()
    db.close()
    return {"ok": True}


@app.delete("/api/brokers/{symbol}")
def delete_broker(symbol: str):
    db = session()
    b = db.get(Broker, symbol.upper())
    if b is None:
        raise HTTPException(404)
    for r in db.query(Report).filter_by(broker=b.symbol).all():
        db.delete(r)
    db.delete(b)
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/export")
def do_export():
    d = export.write()
    return {"reports": len(d["reports"]), "push": export.push()}


@app.get("/api/health")
def health():
    from common.config import ANTHROPIC_API_KEY, EXTRACT_MODEL, LOCATE_MODEL
    return {"api_key": bool(ANTHROPIC_API_KEY), "extract_model": EXTRACT_MODEL, "locate_model": LOCATE_MODEL,
            "now": datetime.now(TZ).isoformat(timespec="seconds")}

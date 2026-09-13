"""Điều phối các bước cho một báo cáo, cập nhật status trong DB để màn hình hàng đợi hiển thị.

Mỗi bước là một hàm nhận report_id; lỗi → status='stuck' + stuck_step + stuck_reason, người dùng
sửa (dán URL, gõ số trang) rồi bấm "Chạy tiếp" → resume() chạy từ bước bị kẹt.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from common import dnse, finfo
from common.config import TZ
from common.quarters import end_date

from . import extract as extractor
from . import fetch as fetcher
from . import locate as locator
from . import slice as pdfslice
from . import validate
from .db import session
from .models import Broker, Holding, Report

logger = logging.getLogger(__name__)

_running: set[int] = set()
_lock = threading.Lock()


def _set(db, rep: Report, status: str, **kw) -> None:
    rep.status = status
    for k, v in kw.items():
        setattr(rep, k, v)
    db.commit()


def _stuck(db, rep: Report, step: str, reason: str) -> None:
    logger.warning("%s %s kẹt ở %s: %s", rep.broker, rep.quarter, step, reason)
    _set(db, rep, "stuck", stuck_step=step, stuck_reason=str(reason)[:1000])


# ---------------------------------------------------------------- các bước

def step_fetch(db, rep: Report, pdf_url: str = "") -> bool:
    _set(db, rep, "fetching", stuck_step="", stuck_reason="")
    b = db.get(Broker, rep.broker)
    try:
        r = fetcher.fetch(rep.broker, rep.quarter, ir_url=b.ir_url if b else "", pdf_url=pdf_url or rep.source_url)
    except Exception as exc:  # noqa: BLE001
        _stuck(db, rep, "fetching", exc)
        return False
    rep.source_url, rep.pdf_path, rep.pdf_sha256 = r["url"], r["path"], r["sha256"]
    rep.page_count = pdfslice.page_count(r["path"])
    db.commit()
    return True


# Trên ngưỡng này mới dùng bước tìm trang (Haiku) — dưới thì đọc cả cuốn cho chắc.
# Đo trên 11 báo cáo Q2/2026: Haiku chọn nhầm bảng cân đối kế toán 8/11 lần, còn Opus đọc cả cuốn
# (nén 90–100 DPI, 40–70 trang) đúng 11/11 với giá ~0,3 USD. Đơn giản hơn thắng.
LOCATE_ABOVE_PAGES = 120


def step_locate(db, rep: Report, pages: list[int] | None = None) -> bool:
    _set(db, rep, "locating", stuck_step="", stuck_reason="")
    if pages:
        rep.note_pages = ",".join(str(p) for p in pages)       # người dùng gõ số trang
    elif rep.page_count and rep.page_count > LOCATE_ABOVE_PAGES:
        try:
            found = locator.locate(rep.pdf_path, rep.page_count)
        except Exception as exc:  # noqa: BLE001
            _stuck(db, rep, "locating", exc)
            return False
        rep.note_pages = ",".join(str(p) for p in locator.expand(found, rep.page_count)) if found else "all"
    else:
        rep.note_pages = "all"
    db.commit()
    return True


def _pages_of(rep: Report) -> list[int] | None:
    if rep.note_pages.strip().lower() == "all":
        return None
    return [int(p) for p in rep.note_pages.split(",") if p.strip().isdigit()] or None


def step_extract(db, rep: Report) -> bool:
    _set(db, rep, "extracting", stuck_step="", stuck_reason="")
    pages = _pages_of(rep)
    try:
        data = extractor.extract(rep.pdf_path, pages, rep.broker, rep.quarter)
        if pages and not (data.get("rows") or []):
            # Trang đã chọn không có bảng (định vị sai) → thử lại với cả cuốn một lần
            logger.info("%s %s: 0 dòng từ trang %s — đọc lại cả cuốn", rep.broker, rep.quarter, rep.note_pages)
            data = extractor.extract(rep.pdf_path, None, rep.broker, rep.quarter)
            rep.note_pages = "all"
    except Exception as exc:  # noqa: BLE001
        _stuck(db, rep, "extracting", exc)
        return False
    # Model trả về trang nguồn (đếm trong tài liệu đã gửi). Đọc cả cuốn → trùng số trang gốc;
    # đọc theo lát → ánh xạ ngược về số trang gốc. Màn duyệt dùng để hiện ảnh đúng trang.
    src = [int(p) for p in (data.get("source_pages") or []) if isinstance(p, (int, float)) and p >= 1]
    if src:
        if pages:
            src = [pages[p - 1] for p in src if p - 1 < len(pages)]
        rep.note_pages = ",".join(str(p) for p in sorted(set(src))[:8])
    apply_extract(db, rep, data, model=extractor.EXTRACT_MODEL)
    return True


def apply_extract(db, rep: Report, data: dict, model: str = "") -> None:
    """Ghi kết quả bóc (từ model hoặc từ fixture/nhập JSON) vào holding, thay toàn bộ dòng cũ."""
    rows = extractor.normalize(data)
    # thay toàn bộ holding cũ (chạy lại = làm lại từ đầu); gán qua quan hệ để delete-orphan lo phần xoá
    rep.holdings = [
        Holding(asset_class=r["asset_class"], ticker=r["ticker"], raw_label=r["raw_label"],
                quantity=r["quantity"], cost_value=r["cost_value"], fair_value=r["fair_value"],
                confidence=r["confidence"], is_listed=r["kind"] == "listed_stock")
        for r in rows
    ]
    rep.model_used = model or rep.model_used
    rep.extracted_at = datetime.now(TZ).replace(tzinfo=None, microsecond=0)
    rep.checks_json = json.dumps({"totals": data.get("totals") or [], "notes": data.get("notes") or "", "usage": data.get("_usage")}, ensure_ascii=False)
    db.commit()


def step_validate(db, rep: Report) -> bool:
    _set(db, rep, "validating", stuck_step="", stuck_reason="")
    rows = [_h2d(h) for h in rep.holdings]
    saved = json.loads(rep.checks_json or "{}")
    try:
        fin = finfo.quarter_totals(rep.broker, rep.quarter)
    except Exception as exc:  # noqa: BLE001
        logger.warning("finfo lỗi: %s", exc)
        fin = None
    tickers = sorted({r["ticker"] for r in rows if r["ticker"]})
    try:
        meta = finfo.stock_meta(tickers)
    except Exception as exc:  # noqa: BLE001
        logger.warning("finfo stocks lỗi: %s", exc)
        meta = {}
    closes: dict[str, float] = {}
    qend = end_date(rep.quarter)
    with dnse.DnseClient(days=400) as c:
        for t in tickers:
            if meta.get(t, {}).get("status") == "listed":
                px = dnse.close_on_or_before(c.daily(t), qend)
                if px:
                    closes[t] = px
    checks = validate.run_all(rows, saved.get("totals") or [], fin, meta, closes)
    validate.imply_quantity(rows, closes)
    for h, r in zip(rep.holdings, rows):
        h.is_listed, h.flags = r.get("is_listed", False), r.get("flags", "")
        if r.get("quantity_source") == "implied":
            h.quantity, h.quantity_source = r["quantity"], "implied"
    saved.update({"checks": checks, "closes": closes})
    rep.checks_json = json.dumps(saved, ensure_ascii=False, default=str)
    rep.finfo_json = json.dumps(fin or {}, ensure_ascii=False)
    _set(db, rep, "review")
    return True


def _h2d(h: Holding) -> dict:
    return {
        "id": h.id, "asset_class": h.asset_class, "ticker": h.ticker, "raw_label": h.raw_label,
        "is_listed": h.is_listed, "quantity": h.quantity, "quantity_source": h.quantity_source,
        "cost_value": h.cost_value, "fair_value": h.fair_value, "flags": h.flags, "deleted": h.deleted,
    }


# ---------------------------------------------------------------- chạy chuỗi

STEPS = ["fetching", "locating", "extracting", "validating"]


def run(report_id: int, from_step: str = "fetching", pdf_url: str = "", pages: list[int] | None = None) -> None:
    """Chạy tuần tự từ from_step. Idempotent: bước đã xong (có pdf, có note_pages) được giữ."""
    with _lock:
        if report_id in _running:
            return
        _running.add(report_id)
    try:
        db = session()
        rep = db.get(Report, report_id)
        if rep is None or rep.status == "approved":
            return
        start = STEPS.index(from_step) if from_step in STEPS else 0
        for step in STEPS[start:]:
            if step == "fetching":
                if rep.pdf_path and not pdf_url and _pdf_ok(rep):
                    continue
                if not step_fetch(db, rep, pdf_url):
                    return
            elif step == "locating":
                if rep.note_pages and not pages:
                    continue
                if not step_locate(db, rep, pages):
                    return
            elif step == "extracting":
                if not step_extract(db, rep):
                    return
            elif step == "validating":
                if not step_validate(db, rep):
                    return
        db.close()
    finally:
        with _lock:
            _running.discard(report_id)


def _pdf_ok(rep: Report) -> bool:
    import os
    return bool(rep.pdf_path) and os.path.exists(rep.pdf_path)


def run_async(report_id: int, **kw) -> None:
    threading.Thread(target=run, args=(report_id,), kwargs=kw, daemon=True).start()


def start_quarter(quarter: str, stmt_type: str = "rieng") -> list[int]:
    """Tạo report cho mọi broker đang bật (nếu chưa có) và chạy nền tuần tự. Trả về id."""
    db = session()
    ids: list[int] = []
    for b in db.query(Broker).filter_by(enabled=True).order_by(Broker.symbol).all():
        rep = db.query(Report).filter_by(broker=b.symbol, quarter=quarter, stmt_type=stmt_type).one_or_none()
        if rep is None:
            rep = Report(broker=b.symbol, quarter=quarter, stmt_type=stmt_type, status="queued")
            db.add(rep)
            db.commit()
        if rep.status != "approved":
            ids.append(rep.id)
    db.close()

    def worker():
        for rid in ids:
            run(rid)

    threading.Thread(target=worker, daemon=True).start()
    return ids


def is_running(report_id: int) -> bool:
    return report_id in _running

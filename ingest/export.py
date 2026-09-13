"""Bước 6 — gom mọi báo cáo đã chốt thành data/holdings.json rồi commit + push.

Chỉ status='approved' mới được xuất. Mỗi dòng mang nhãn nguồn (disclosed/implied/manual) để
giao diện và job hiển thị đúng. Kèm số tổng finfo để công ty không thuyết minh (SSI) vẫn có
"quy mô tự doanh".
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime

from common.config import ROOT, SITE_DATA, TZ

from .db import session
from .models import Broker, Report

OUT = SITE_DATA / "holdings.json"


def build() -> dict:
    db = session()
    brokers = [{"symbol": b.symbol, "name": b.name, "floor": b.floor, "enabled": b.enabled}
               for b in db.query(Broker).order_by(Broker.symbol).all()]
    reports = []
    for rep in db.query(Report).filter_by(status="approved").order_by(Report.broker, Report.quarter).all():
        rows = []
        for h in rep.holdings:
            if h.deleted:
                continue
            rows.append({
                "asset_class": h.asset_class, "ticker": h.ticker, "raw_label": h.raw_label,
                "is_listed": h.is_listed,
                "quantity": h.quantity, "quantity_source": h.quantity_source,
                "cost_value": h.cost_value, "cost_source": h.cost_source,
                "fair_value": h.fair_value, "fair_source": h.fair_source,
            })
        reports.append({
            "broker": rep.broker, "quarter": rep.quarter, "stmt_type": rep.stmt_type,
            "approved_at": rep.approved_at.isoformat() if rep.approved_at else None,
            "source_url": rep.source_url, "note_pages": rep.note_pages,
            "totals": json.loads(rep.finfo_json or "{}"),
            "holdings": rows,
        })
    db.close()
    return {"generated_at": datetime.now(TZ).isoformat(timespec="seconds"), "brokers": brokers, "reports": reports}


def write() -> dict:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    from . import stamp  # đóng dấu phiên bản giao diện mỗi lần xuất
    stamp.stamp()
    return data


def push(message: str = "") -> str:
    """git add/commit/push holdings.json. Trả về mô tả kết quả (không ném lỗi — hiện trên UI)."""
    msg = message or f"holdings: cập nhật {datetime.now(TZ):%d/%m/%Y %H:%M}"
    # Máy chưa cấu hình user.name/email thì git commit thất bại im lặng → luôn truyền danh tính công cụ.
    git = ["git", "-c", "user.name=TuDoanh Radar", "-c", "user.email=tudoanh-radar@local"]
    try:
        subprocess.run(git + ["add", str(OUT.relative_to(ROOT)), "docs/index.html", "docs/app.js"], cwd=ROOT, check=True, capture_output=True)
        r = subprocess.run(git + ["commit", "-m", msg], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            if "nothing to commit" in (r.stdout + r.stderr):
                return "Không có gì thay đổi so với lần đẩy trước"
            return f"git commit lỗi: {(r.stderr or r.stdout).strip()[:300]}"
        remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        if not remotes:
            return "Đã commit local. Chưa cấu hình remote GitHub nên chưa push (xem README)"
        p = subprocess.run(git + ["push"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        return "Đã đẩy lên GitHub" if p.returncode == 0 else f"Push lỗi: {p.stderr.strip()[:300]}"
    except subprocess.CalledProcessError as exc:
        return f"git lỗi: {(exc.stderr or b'').decode(errors='ignore')[:300]}"


if __name__ == "__main__":
    d = write()
    print(f"Đã ghi {OUT} — {len(d['reports'])} báo cáo đã chốt")
    print(push())

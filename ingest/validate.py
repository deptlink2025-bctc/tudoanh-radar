"""Bước 4 — bốn kiểm tra đối chiếu, chặn các lỗi OCR kinh điển trước khi cho duyệt.

1. Tổng các dòng khớp dòng "Cộng" trong chính bảng (≤ 0,5 %).
2. FVTPL + AFS + HTM đối chiếu số tổng từ finfo cùng kỳ (≤ 2 % — riêng lẻ vs hợp nhất có thể lệch).
3. Mọi ticker phải tồn tại và đang niêm yết; không → is_listed = False (trái phiếu, OTC, CCQ).
4. quantity × giá đóng cửa cuối quý phải nằm trong ±15 % fair_value; lệch → cờ đỏ, gần như chắc
   chắn OCR sai chữ số.

Hàm thuần: nhận rows + dữ liệu đối chiếu, trả về (rows đã gắn cờ, checks). Không gọi mạng —
pipeline lo phần lấy finfo / giá để test được offline.
"""
from __future__ import annotations

from datetime import date

TOL_TOTAL = 0.005
TOL_FINFO = 0.02
TOL_QTY_PRICE = 0.15


def _pct(a: float | None, b: float | None) -> float | None:
    if not a or not b:
        return None
    return abs(a - b) / abs(b)


def check_totals(rows: list[dict], totals: list[dict]) -> dict:
    """Kiểm tra 1. Với mỗi asset_class: so tổng cost/fair các dòng với dòng Cộng LỚN NHẤT của
    nhóm đó (bảng hay có tổng phụ kiểu 'Cổ phiếu' nằm trong FVTPL — không so với tổng phụ)."""
    detail = []
    ok = True
    by_class: dict[str, dict] = {}
    for r in rows:
        if r.get("deleted"):
            continue
        d = by_class.setdefault(r["asset_class"], {"cost": 0.0, "fair": 0.0})
        d["cost"] += r.get("cost_value") or 0
        d["fair"] += r.get("fair_value") or 0
    biggest: dict[str, dict] = {}
    for t in totals or []:
        ac = t["asset_class"]
        key = max(t.get("cost_value") or 0, t.get("fair_value") or 0)
        if ac not in biggest or key > max(biggest[ac].get("cost_value") or 0, biggest[ac].get("fair_value") or 0):
            biggest[ac] = t
    for ac, t in biggest.items():
        got = by_class.get(ac)
        if not got:
            continue
        for key, want in (("cost", t.get("cost_value")), ("fair", t.get("fair_value"))):
            if want is None:
                continue
            p = _pct(got[key], want)
            good = p is not None and p <= TOL_TOTAL
            ok = ok and good
            detail.append({"asset_class": ac, "field": key, "sum": got[key], "total": want, "pct": p, "ok": good})
    if not totals:
        return {"id": "totals", "ok": None, "msg": "Bảng không có dòng Cộng để đối chiếu", "detail": []}
    worst = max((d["pct"] or 0) for d in detail) if detail else 0
    return {
        "id": "totals", "ok": ok,
        "msg": ("Khớp dòng “Cộng” — lệch tối đa %.2f%%" % (worst * 100)) if ok
        else "Tổng các dòng KHÔNG khớp dòng “Cộng” — lệch %.1f%%; có dòng đọc sai hoặc thiếu" % (worst * 100),
        "detail": detail,
    }


def check_finfo(rows: list[dict], finfo: dict | None) -> dict:
    """Kiểm tra 2. So FVTPL+AFS+HTM (fair) với 'Tài sản tài chính ngắn hạn' finfo — đây là số
    bao gồm cả cho vay margin, nên chỉ so được theo hướng: bóc ra KHÔNG ĐƯỢC LỚN HƠN số finfo,
    và AFS/HTM riêng lẻ so trực tiếp nếu finfo có."""
    if not finfo:
        return {"id": "finfo", "ok": None, "msg": "VNDirect chưa có số kỳ này để đối chiếu", "detail": []}
    fair = {"FVTPL": 0.0, "AFS": 0.0, "HTM": 0.0}
    for r in rows:
        if not r.get("deleted"):
            fair[r["asset_class"]] += r.get("fair_value") or 0
    detail, ok = [], True
    total = sum(fair.values())
    st = finfo.get("st_fin_assets")
    if st:
        over = total > st * (1 + TOL_FINFO)
        ok = ok and not over
        detail.append({"field": "tổng FVTPL+AFS+HTM ≤ TSTC ngắn hạn", "sum": total, "ref": st, "ok": not over})
    for key, name in (("afs", "AFS"), ("htm", "HTM")):
        ref = finfo.get(key)
        if ref and fair[name]:
            p = _pct(fair[name], ref)
            good = p is not None and p <= TOL_FINFO
            ok = ok and good
            detail.append({"field": name, "sum": fair[name], "ref": ref, "pct": p, "ok": good})
    return {
        "id": "finfo", "ok": ok,
        "msg": "Khớp số tổng VNDirect cùng kỳ" if ok else "Lệch số tổng VNDirect quá 2% — xem lại đơn vị (nghìn/triệu đồng) hoặc thiếu trang",
        "detail": detail,
    }


def check_listed(rows: list[dict], meta: dict[str, dict]) -> dict:
    """Kiểm tra 3. Gắn is_listed; đếm mã không tra được."""
    unknown = []
    for r in rows:
        t = r.get("ticker") or ""
        m = meta.get(t)
        listed = bool(t) and m is not None and m.get("status") == "listed" and m.get("type") == "STOCK"
        r["is_listed"] = listed
        if t and not listed:
            unknown.append(t)
            r["flags"] = _add_flag(r.get("flags", ""), "unlisted")
    return {
        "id": "listed", "ok": True,
        "msg": "Mọi mã cổ phiếu đều đang niêm yết" if not unknown
        else f"{len(unknown)} dòng không phải cổ phiếu niêm yết (trái phiếu/OTC), đã đánh dấu: " + ", ".join(unknown[:8]),
        "detail": unknown,
    }


def check_qty_price(rows: list[dict], closes: dict[str, float]) -> dict:
    """Kiểm tra 4. quantity × close cuối quý so với fair_value."""
    bad = []
    for r in rows:
        if r.get("deleted") or not r.get("is_listed"):
            continue
        q, fv, px = r.get("quantity"), r.get("fair_value"), closes.get(r.get("ticker") or "")
        if not q or not fv or not px:
            continue
        p = _pct(q * px, fv)
        if p is not None and p > TOL_QTY_PRICE:
            r["flags"] = _add_flag(r.get("flags", ""), "qty_price_mismatch")
            bad.append({"ticker": r["ticker"], "qty": q, "close": px, "implied": q * px, "fair": fv, "pct": p})
    return {
        "id": "qty_price", "ok": not bad,
        "msg": "KL × giá cuối quý khớp giá trị hợp lý (±15%)" if not bad
        else f"{len(bad)} dòng có KL × giá lệch quá 15% so với giá trị hợp lý — nhiều khả năng OCR đọc nhầm cột: " + ", ".join(b["ticker"] for b in bad),
        "detail": bad,
    }


def imply_quantity(rows: list[dict], closes: dict[str, float]) -> int:
    """Thiếu KL mà có giá trị hợp lý + giá cuối quý → KL ước tính. Trả về số dòng suy."""
    n = 0
    for r in rows:
        if r.get("quantity") is None and r.get("is_listed") and r.get("fair_value") and closes.get(r.get("ticker") or ""):
            r["quantity"] = round(r["fair_value"] / closes[r["ticker"]])
            r["quantity_source"] = "implied"
            n += 1
    return n


def run_all(rows: list[dict], totals: list[dict], finfo: dict | None, meta: dict[str, dict], closes: dict[str, float]) -> list[dict]:
    """Chạy 4 kiểm tra theo thứ tự; check 3 phải trước check 4 (cần is_listed)."""
    return [
        check_totals(rows, totals),
        check_finfo(rows, finfo),
        check_listed(rows, meta),
        check_qty_price(rows, closes),
    ]


def _add_flag(flags: str, f: str) -> str:
    s = set(x for x in (flags or "").split(";") if x)
    s.add(f)
    return ";".join(sorted(s))


def quarter_close_date(quarter_end: date) -> date:
    return quarter_end

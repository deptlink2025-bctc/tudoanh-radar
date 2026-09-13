"""So sánh hai ảnh chụp cuối quý của một công ty, ghép theo mã → MỚI / MUA THÊM / BÁN BỚT / BÁN HẾT / GIỮ NGUYÊN.

Giá trị: MỚI = GTHL quý này; BÁN HẾT = GTHL quý trước; MUA THÊM/BÁN BỚT = ΔKL × giá đóng cửa cuối quý này.
Giới hạn nói thật: mua rồi bán hết trong quý là vô hình.
"""
from __future__ import annotations

from collections import defaultdict

KINDS = {"new": "MỚI", "add": "MUA THÊM", "cut": "BÁN BỚT", "out": "BÁN HẾT", "hold": "GIỮ NGUYÊN"}


def _by_ticker(holdings: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for h in holdings:
        t = h.get("ticker")
        if not t or not h.get("is_listed"):
            continue
        d = out.setdefault(t, {"qty": 0.0, "fair": 0.0, "cost": 0.0, "has_qty": True})
        if h.get("quantity") is None:
            d["has_qty"] = False
        else:
            d["qty"] += h["quantity"]
        d["fair"] += h.get("fair_value") or 0
        d["cost"] += h.get("cost_value") or 0
    return out


def diff_quarters(prev_h: list[dict], cur_h: list[dict], closes_cur: dict[str, float]) -> dict:
    a, b = _by_ticker(prev_h), _by_ticker(cur_h)
    rows: list[dict] = []
    buy = sell = 0.0
    for t in sorted(set(a) | set(b)):
        p, c = a.get(t), b.get(t)
        px = closes_cur.get(t)
        if p is None:
            kind, value = "new", c["fair"]
        elif c is None:
            kind, value = "out", -p["fair"]
        elif not (p["has_qty"] and c["has_qty"]):
            # thiếu KL một trong hai kỳ → so theo giá trị hợp lý (ước)
            dv = c["fair"] - p["fair"]
            kind = "hold" if abs(dv) <= 0.02 * max(p["fair"], 1) else ("add" if dv > 0 else "cut")
            value = dv if kind != "hold" else 0.0
        else:
            dq = c["qty"] - p["qty"]
            if abs(dq) <= 0.005 * max(p["qty"], 1):
                kind, value = "hold", 0.0
            else:
                kind = "add" if dq > 0 else "cut"
                value = dq * (px or (c["fair"] / c["qty"] if c["qty"] else 0))
        if value > 0:
            buy += value
        elif value < 0:
            sell += -value
        rows.append({
            "ticker": t, "kind": kind, "label": KINDS[kind],
            "q0": p["qty"] if p else None, "q1": c["qty"] if c else None,
            "v0": p["fair"] if p else None, "v1": c["fair"] if c else None,
            "value": value,
        })
    order = {"new": 0, "add": 1, "cut": 2, "out": 3, "hold": 4}
    rows.sort(key=lambda r: (order[r["kind"]], -abs(r["value"])))
    return {"rows": rows, "buy": buy, "sell": sell, "n0": len(a), "n1": len(b)}


def industry_rollup(diffs: dict[str, dict]) -> list[dict]:
    """Cộng dồn theo mã qua nhiều công ty: mã nào được gom/xả nhiều nhất."""
    agg: dict[str, dict] = defaultdict(lambda: {"n_new": 0, "n_add": 0, "n_cut": 0, "n_out": 0, "net": 0.0, "brokers": []})
    for broker, d in diffs.items():
        for r in d["rows"]:
            if r["kind"] == "hold":
                continue
            g = agg[r["ticker"]]
            g["n_" + r["kind"]] += 1
            g["net"] += r["value"]
            g["brokers"].append(broker)
    out = [{"ticker": t, **v} for t, v in agg.items()]
    out.sort(key=lambda x: -abs(x["net"]))
    return out

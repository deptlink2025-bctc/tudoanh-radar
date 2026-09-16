"""Mark-to-market: từ holdings đã chốt + giá DNSE → giá trị hôm nay, hôm qua, từ cuối quý, so giá vốn.

Hàm thuần, không gọi mạng: nhận holdings + dict giá để test offline.
`bars[ticker]` = danh sách nến ngày (VND) cũ → mới, như common.dnse trả về.
"""
from __future__ import annotations

from datetime import date

from common.dnse import close_on_or_before


def latest_report(reports: list[dict], broker: str) -> dict | None:
    """Báo cáo đã chốt mới nhất của một công ty (ưu tiên riêng lẻ nếu cùng quý)."""
    mine = [r for r in reports if r["broker"] == broker]
    if not mine:
        return None
    mine.sort(key=lambda r: (r["quarter"], r["stmt_type"] == "rieng"))
    return mine[-1]


def report_for(reports: list[dict], broker: str, quarter: str) -> dict | None:
    mine = [r for r in reports if r["broker"] == broker and r["quarter"] == quarter]
    mine.sort(key=lambda r: r["stmt_type"] == "rieng")
    return mine[-1] if mine else None


def value_holdings(holdings: list[dict], bars: dict[str, list[dict]], quarter_end: date,
                   trade_date: date | None = None) -> dict:
    """Trả về {tracked: [...], other_fair, n_tracked, today, since_quarter, vs_cost}.

    `trade_date` = ngày phiên của lần chạy. Mã không có nến ngày đó (không khớp lệnh — IDP chỉ
    100 cp/phiên, đứng im từ 07/09/2026) thì biến động hôm nay = 0 và `stale_days` > 0; nếu
    không kiểm tra, job sẽ đem mức ±15% của phiên cũ ra báo lại mỗi ngày (đã xảy ra 14–16/09/2026).
    `None` = tin hai nến cuối (chỉ dùng trong test cũ).

    tracked = dòng cổ phiếu niêm yết có KL (công bố/ước tính/nhập tay) và có giá.
    other_fair = giá trị hợp lý của phần còn lại (trái phiếu, OTC, 'cổ phiếu khác') — không mark được.
    """
    tracked: list[dict] = []
    other_fair = 0.0
    for h in holdings:
        fv = h.get("fair_value") or 0.0
        t = h.get("ticker") or ""
        b = bars.get(t) or []
        if not (h.get("is_listed") and t and b):
            other_fair += fv
            continue
        qty = h.get("quantity")
        qsrc = h.get("quantity_source") or "disclosed"
        if qty is None:
            qend = close_on_or_before(b, quarter_end)
            if fv and qend:
                qty, qsrc = round(fv / qend), "implied"
        if not qty:
            other_fair += fv
            continue
        last = b[-1]
        close = last["c"]
        stale_days = 0
        if trade_date is None or last["d"] == trade_date:
            prev = b[-2]["c"] if len(b) > 1 else close
        else:
            # Không khớp lệnh trong phiên này → không có biến động hôm nay; giữ giá cuối cùng đã biết.
            prev = close
            stale_days = (trade_date - last["d"]).days
        mv = qty * close
        row = {
            "ticker": t, "asset_class": h.get("asset_class"),
            "quantity": qty, "quantity_source": qsrc,
            "cost_value": h.get("cost_value"), "cost_source": h.get("cost_source") or "disclosed",
            "fair_value": fv or None, "fair_source": h.get("fair_source") or "disclosed",
            "close": close, "prev_close": prev, "trade_date": last["d"].isoformat(), "stale_days": stale_days,
            "market_value": mv, "d1": qty * (close - prev), "p1": round((close / prev - 1) * 100, 4) if prev else 0.0,
            "since_q": (mv - fv) if fv else None,
            "vs_cost": (mv - h["cost_value"]) if h.get("cost_value") else None,
        }
        tracked.append(row)

    tot_mv = sum(r["market_value"] for r in tracked)
    tot_prev = sum(r["quantity"] * r["prev_close"] for r in tracked)
    tot_fv = sum(r["fair_value"] or 0 for r in tracked)
    with_cost = [r for r in tracked if r["cost_value"]]
    tot_cost = sum(r["cost_value"] for r in with_cost)
    mv_with_cost = sum(r["market_value"] for r in with_cost)
    whole = tot_fv + other_fair
    for r in tracked:
        r["weight"] = (r["fair_value"] or 0) / whole if whole else 0.0
    tracked.sort(key=lambda r: r["d1"])
    return {
        "tracked": tracked, "n_tracked": len(tracked), "other_fair": other_fair,
        "today": {"value": tot_mv, "prev_value": tot_prev, "change": tot_mv - tot_prev,
                  "pct": (tot_mv / tot_prev - 1) * 100 if tot_prev else 0.0} if tracked else None,
        "since_quarter": {"change": tot_mv - tot_fv, "pct": (tot_mv / tot_fv - 1) * 100 if tot_fv else 0.0} if tracked else None,
        "vs_cost": {"cost": tot_cost, "value": mv_with_cost, "change": mv_with_cost - tot_cost,
                    "pct": (mv_with_cost / tot_cost - 1) * 100 if tot_cost else 0.0,
                    "n_missing": len(tracked) - len(with_cost)} if with_cost else None,
    }

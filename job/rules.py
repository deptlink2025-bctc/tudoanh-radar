"""Bốn quy tắc cảnh báo. Hàm thuần: nhận kết quả định giá + settings + state, trả về cảnh báo và state mới.

R1  một mã ±X % trong phiên  VÀ  CTCK giữ ≥ Y VND mã đó (điều kiện kép để mã nhỏ không rung chuông)
R2  danh mục một CTCK ±Z VND trong phiên
R3  mã chiếm > W % danh mục chạm sàn/trần (|p1| ≥ r3_pct)
R4  lãi/lỗ so giá vốn của CTCK lần đầu vượt ±V % (nhớ trạng thái để không lặp mỗi ngày)

Chạy 1 lần/ngày nên "1 lần/phiên" là tự nhiên; chỉ R4 cần state.
"""
from __future__ import annotations


def _ty(v: float) -> str:
    return f"{v / 1e9:,.0f}".replace(",", ".")


def evaluate(broker: str, val: dict, settings: dict, state: dict) -> tuple[list[dict], dict]:
    alerts: list[dict] = []
    st = dict(state or {})
    if not val or not val.get("tracked"):
        return alerts, st

    r1_pct, r1_min = float(settings["r1_pct"]), float(settings["r1_min_value"])
    r2 = float(settings["r2_value"])
    r3_w, r3_pct = float(settings["r3_weight"]), float(settings["r3_pct"])
    r4 = float(settings["r4_pct"])

    for r in val["tracked"]:
        p1, mv = r["p1"], r["market_value"]
        if r["weight"] > r3_w and abs(p1) >= r3_pct:
            alerts.append({
                "rule": "R3", "broker": broker, "ticker": r["ticker"], "hot": True,
                "title": f"{broker} · {r['ticker']} {'giảm sàn' if p1 < 0 else 'tăng trần'} {p1:+.1f}%",
                "body": f"{r['ticker']} chiếm {r['weight'] * 100:.0f}% danh mục {broker} · {'mất' if r['d1'] < 0 else 'thêm'} {_ty(abs(r['d1']))} tỷ trong phiên",
            })
        elif abs(p1) >= r1_pct and mv >= r1_min:
            alerts.append({
                "rule": "R1", "broker": broker, "ticker": r["ticker"], "hot": False,
                "title": f"{broker} · {r['ticker']} {p1:+.1f}%",
                "body": f"Giá trị nắm giữ {_ty(mv)} tỷ · {'mất' if r['d1'] < 0 else 'thêm'} {_ty(abs(r['d1']))} tỷ trong phiên",
            })

    today = val.get("today")
    if today and abs(today["change"]) >= r2:
        worst = val["tracked"][0] if today["change"] < 0 else val["tracked"][-1]
        alerts.append({
            "rule": "R2", "broker": broker, "ticker": "", "hot": True,
            "title": f"{broker} · danh mục {'mất' if today['change'] < 0 else 'thêm'} {_ty(abs(today['change']))} tỷ trong phiên",
            "body": f"{today['pct']:+.2f}% so kết phiên hôm qua · {worst['ticker']} {worst['p1']:+.1f}% kéo {_ty(abs(worst['d1']))} tỷ",
        })

    vc = val.get("vs_cost")
    if vc:
        side = "+" if vc["pct"] >= r4 else "-" if vc["pct"] <= -r4 else None
        prev = st.get("r4")
        if side and side != prev:
            alerts.append({
                "rule": "R4", "broker": broker, "ticker": "", "hot": side == "-",
                "title": f"{broker} · {'lãi' if side == '+' else 'lỗ'} so giá vốn vượt {r4:.0f}%",
                "body": f"{vc['pct']:+.1f}% · {_ty(abs(vc['change']))} tỷ trên giá vốn {_ty(vc['cost'])} tỷ · chỉ báo lần đầu chạm",
            })
        st["r4"] = side
    return alerts, st

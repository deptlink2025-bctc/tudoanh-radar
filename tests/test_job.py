"""valuation + diff + rules — hàm thuần, không mạng."""
from datetime import date, timedelta

from job import diff, rules, settings, valuation


def bars(closes):
    """closes cũ→mới → nến ngày giả (VND)."""
    d0 = date(2026, 6, 20)
    return [{"d": d0 + timedelta(days=i), "c": c, "o": c, "h": c, "l": c, "v": 1, "t": i} for i, c in enumerate(closes)]


HOLD = [
    {"asset_class": "FVTPL", "ticker": "HPG", "is_listed": True, "quantity": 1_000_000, "quantity_source": "disclosed",
     "cost_value": 20e9, "fair_value": 25e9},
    {"asset_class": "FVTPL", "ticker": "VHM", "is_listed": True, "quantity": None, "quantity_source": "disclosed",
     "cost_value": None, "fair_value": 40e9},
    {"asset_class": "FVTPL", "ticker": "", "is_listed": False, "quantity": None, "cost_value": 100e9, "fair_value": 110e9},
]
QEND = date(2026, 6, 30)
BARS = {
    "HPG": bars([25_000] * 11 + [26_000, 24_180]),   # cuối quý 25.000, hôm qua 26.000, hôm nay 24.180 (−7%)
    "VHM": bars([40_000] * 11 + [40_000, 41_200]),   # +3%
}


def test_value_holdings_implied_and_today():
    v = valuation.value_holdings(HOLD, BARS, QEND)
    assert v["n_tracked"] == 2 and v["other_fair"] == 110e9
    hpg = [r for r in v["tracked"] if r["ticker"] == "HPG"][0]
    vhm = [r for r in v["tracked"] if r["ticker"] == "VHM"][0]
    assert vhm["quantity"] == 1_000_000 and vhm["quantity_source"] == "implied"
    assert round(hpg["p1"], 1) == -7.0 and hpg["d1"] == 1_000_000 * (24_180 - 26_000)
    assert v["today"]["change"] == hpg["d1"] + vhm["d1"]
    assert v["vs_cost"]["n_missing"] == 1               # VHM không có giá gốc
    assert v["vs_cost"]["cost"] == 20e9


def test_stale_ticker_has_no_today_change_and_no_alert():
    """Mã không khớp lệnh trong phiên (IDP 07→16/09/2026) không được mang biến động cũ đi mãi."""
    today = BARS["HPG"][-1]["d"]
    stale = {**BARS, "HPG": BARS["HPG"][:-3]}          # nến cuối của HPG cách phiên 3 ngày
    assert stale["HPG"][-1]["d"] == today - timedelta(days=3)
    v = valuation.value_holdings(HOLD, stale, QEND, trade_date=today)
    hpg = [r for r in v["tracked"] if r["ticker"] == "HPG"][0]
    vhm = [r for r in v["tracked"] if r["ticker"] == "VHM"][0]
    assert hpg["d1"] == 0 and hpg["p1"] == 0.0 and hpg["stale_days"] == 3
    assert hpg["close"] == 25_000 and hpg["market_value"] == 1_000_000 * 25_000  # giá cuối cùng đã biết
    assert vhm["stale_days"] == 0 and round(vhm["p1"], 1) == 3.0            # mã có nến hôm nay: như cũ
    assert v["today"]["change"] == vhm["d1"]
    al, _ = rules.evaluate("XYZ", v, dict(settings.DEFAULTS), {})
    assert not [a for a in al if a["ticker"] == "HPG" and a["rule"] in ("R1", "R3")]
    # Không truyền trade_date → hành vi cũ (hai nến cuối), HPG vẫn −7 %
    old = valuation.value_holdings(HOLD, BARS, QEND)
    assert round([r for r in old["tracked"] if r["ticker"] == "HPG"][0]["p1"], 1) == -7.0


def test_rules_r1_needs_both_conditions():
    v = valuation.value_holdings(HOLD, BARS, QEND)
    cfg = dict(settings.DEFAULTS)
    al, st = rules.evaluate("XYZ", v, cfg, {})
    r1 = [a for a in al if a["rule"] == "R1"]
    assert r1 and r1[0]["ticker"] == "HPG"              # −7 % và giữ 24 tỷ ≥ 20 tỷ
    cfg["r1_min_value"] = 50e9
    al, _ = rules.evaluate("XYZ", v, cfg, {})
    assert not [a for a in al if a["rule"] == "R1"]     # cùng −7 % nhưng giá trị nhỏ → im


def test_rules_r3_weight_and_r4_first_touch_only():
    v = valuation.value_holdings(HOLD, BARS, QEND)
    cfg = dict(settings.DEFAULTS)
    cfg["r3_weight"] = 0.10                             # HPG chiếm 25/175 ≈ 14 %
    al, st = rules.evaluate("XYZ", v, cfg, {})
    assert [a["rule"] for a in al if a["ticker"] == "HPG"] == ["R3"]
    # R4: HPG 20 tỷ vốn → 24,18 tỷ = +20,9 % ≥ 15 % → bắn lần đầu, không bắn lần hai
    assert any(a["rule"] == "R4" for a in al) and st["r4"] == "+"
    al2, st2 = rules.evaluate("XYZ", v, cfg, st)
    assert not any(a["rule"] == "R4" for a in al2)


def test_diff_five_kinds():
    prev = [
        {"ticker": "HPG", "is_listed": True, "quantity": 1_000_000, "fair_value": 25e9},
        {"ticker": "NVL", "is_listed": True, "quantity": 2_000_000, "fair_value": 30e9},
        {"ticker": "MWG", "is_listed": True, "quantity": 500_000, "fair_value": 40e9},
        {"ticker": "VHM", "is_listed": True, "quantity": 100_000, "fair_value": 4e9},
    ]
    cur = [
        {"ticker": "HPG", "is_listed": True, "quantity": 1_500_000, "fair_value": 36e9},
        {"ticker": "MWG", "is_listed": True, "quantity": 200_000, "fair_value": 16e9},
        {"ticker": "VHM", "is_listed": True, "quantity": 100_000, "fair_value": 4.1e9},
        {"ticker": "VIC", "is_listed": True, "quantity": 300_000, "fair_value": 12e9},
    ]
    d = diff.diff_quarters(prev, cur, {"HPG": 24_000, "MWG": 80_000, "VIC": 40_000})
    kinds = {r["ticker"]: r["kind"] for r in d["rows"]}
    assert kinds == {"VIC": "new", "HPG": "add", "MWG": "cut", "NVL": "out", "VHM": "hold"}
    assert d["buy"] == 12e9 + 500_000 * 24_000
    assert d["sell"] == 30e9 + 300_000 * 80_000
    roll = diff.industry_rollup({"A": d, "B": d})
    assert roll[0]["ticker"] in ("NVL", "MWG") and roll[0]["n_out"] + roll[0]["n_cut"] == 2

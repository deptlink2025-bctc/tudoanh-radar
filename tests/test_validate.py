"""4 kiểm tra đối chiếu trên fixture SHS Q2/2026 (chép tay từ trang 24 BCTC thật)."""
import json
from pathlib import Path

from ingest import extract, validate

FIX = json.loads((Path(__file__).parent / "fixtures" / "shs_2026q2_extract.json").read_text(encoding="utf-8"))
FINFO = {"fiscalDate": "2026-06-30", "total_assets": 27566961471493.0, "st_fin_assets": 27432885244024.0,
         "afs": 1418006484550.0, "htm": 749808987855.0}
META = {t: {"status": "listed", "type": "STOCK", "floor": "HOSE"} for t in ["CTG", "HPG", "HCM", "MWG", "SHB", "TCD"]}
CLOSES = {"CTG": 33440.0, "HCM": 23450.0, "HPG": 23300.0, "MWG": 76900.0, "SHB": 13550.0, "TCD": 1890.0}


def rows():
    return extract.normalize(FIX)


def test_normalize_keeps_unnamed_lines():
    r = rows()
    assert len(r) == 12
    assert sum(1 for x in r if x["ticker"] == "") == 6      # cổ phiếu khác, trái phiếu, CCQ, ...
    assert all(x["cost_value"] is None or x["cost_value"] > 1e6 for x in r)


def test_check_totals_uses_biggest_total_per_class():
    c = validate.check_totals(rows(), FIX["totals"])
    assert c["ok"] is True
    # tổng phụ "Cổ phiếu" 3.045 tỷ KHÔNG được dùng để so với tổng FVTPL 11.205 tỷ
    assert all(d["pct"] < 0.005 for d in c["detail"])


def test_check_totals_catches_a_wrong_digit():
    r = rows()
    r[5]["cost_value"] = 8094052576267 * 10       # OCR đọc dư một chữ số ở dòng trái phiếu
    assert validate.check_totals(r, FIX["totals"])["ok"] is False


def test_check_finfo_afs_exact_match():
    c = validate.check_finfo(rows(), FINFO)
    assert c["ok"] is True
    afs = [d for d in c["detail"] if d["field"] == "AFS"][0]
    assert afs["pct"] < 1e-9                        # 1.418.006.484.550 khớp từng đồng


def test_check_finfo_flags_unit_error():
    r = rows()
    for x in r:
        for k in ("cost_value", "fair_value"):
            if x[k]:
                x[k] *= 1000                        # quên nhân đơn vị "nghìn đồng"
    assert validate.check_finfo(r, FINFO)["ok"] is False


def test_listed_and_implied_quantity():
    r = rows()
    validate.check_listed(r, META)
    assert [x["ticker"] for x in r if x["is_listed"]] == ["CTG", "HPG", "HCM", "MWG", "SHB", "TCD"]
    n = validate.imply_quantity(r, CLOSES)
    assert n == 6
    hpg = [x for x in r if x["ticker"] == "HPG"][0]
    assert hpg["quantity"] == 5451000 and hpg["quantity_source"] == "implied"
    assert validate.check_qty_price(r, CLOSES)["ok"] is True


def test_qty_price_mismatch_flag():
    r = rows()
    validate.check_listed(r, META)
    hpg = [x for x in r if x["ticker"] == "HPG"][0]
    hpg["quantity"] = 54510000                       # thừa một số 0
    c = validate.check_qty_price(r, CLOSES)
    assert c["ok"] is False and "qty_price_mismatch" in hpg["flags"]


def test_unknown_ticker_marked_unlisted():
    r = rows()
    r[0]["ticker"] = "TCB2426"
    validate.check_listed(r, META)
    assert r[0]["is_listed"] is False and "unlisted" in r[0]["flags"]

from datetime import date

import pytest

from common import quarters
from ingest import fetch


def test_quarter_basics():
    assert quarters.end_date("2026Q2") == date(2026, 6, 30)
    assert quarters.prev("2026Q1") == "2025Q4"
    assert quarters.label("2026Q3") == "Q3/2026"
    with pytest.raises(ValueError):
        quarters.parse("Q2-2026")


def test_latest_reported_waits_20_days():
    # 13/09: Q2 kết thúc 30/06 đã > 20 ngày → Q2
    assert quarters.latest_reported(date(2026, 9, 13)) == "2026Q2"
    # 05/07: Q2 mới 5 ngày → vẫn Q1
    assert quarters.latest_reported(date(2026, 7, 5)) == "2026Q1"
    # 25/01: Q4/2025 đã 25 ngày → Q4/2025
    assert quarters.latest_reported(date(2026, 1, 25)) == "2025Q4"


# Các tên file thật gặp trên trang IR của SSI và SHS (13/09/2026)
SSI_RIENG_Q2 = "https://www.ssi.com.vn/upload/files/IR/Reports/IR/20260720_SSI_Bao_cao_tai_chinh_rieng_Quy_2_nam_2026.pdf"
SSI_HOPNHAT_Q2 = "https://www.ssi.com.vn/upload/files/IR/20260730%20-%20SSI%20-%20Bao%20cao%20tai%20chinh%20hop%20nhat%20Quy%202%20nam%202026_signed.pdf"
SSI_SOATXET = "https://www.ssi.com.vn/upload/files/IR/20260814_SSI_Bao_cao_tai_chinh_rieng_soat_xet_ban_nien_2026.pdf"
SHS_Q1 = "https://s3-storage.shs.com.vn/shs-website/VI_SHS_BC_Quy_Bao_Cao_Tai_Chinh_Q1_2026_UB_d02d7aca72.pdf"
SHS_Q2 = "https://s3-storage.shs.com.vn/shs-website/VI_SHS_Bao_Cao_Tai_Chinh_Q2_2026_UB_034c3261d1.pdf"


def test_score_prefers_separate_report_of_right_quarter():
    s = lambda u, q="2026Q2": fetch.score_candidate(u, "", q)  # noqa: E731
    assert s(SSI_RIENG_Q2) > s(SSI_HOPNHAT_Q2) >= 5
    assert s(SSI_SOATXET) < 5            # bán niên soát xét không phải BCTC quý
    assert s(SHS_Q2) >= 5
    assert s(SHS_Q1) < 0                 # sai quý → loại hẳn
    assert s(SHS_Q1, "2026Q1") >= 5


def test_resolve_ir_template():
    assert fetch.resolve_ir_url("https://x/bctc-quy-{q}-nam-{y}", "2026Q3") == "https://x/bctc-quy-3-nam-2026"

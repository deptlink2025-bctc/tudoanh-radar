"""15 CTCK mặc định + trang IR để tự tìm PDF BCTC quý.

`ir_url` là trang liệt kê báo cáo của chính công ty; fetch.py quét link .pdf và chấm điểm theo
quý. Để TRỐNG thì đi thẳng sang nguồn dự phòng Vietstock (ingest/vietstock.py) — đa số web CTCK
dựng bằng JS hoặc chặn máy nên chỉ SSI, SHS, HCM giữ trang IR riêng (xác minh 13/09/2026).
"""
from __future__ import annotations

DEFAULT_BROKERS: list[dict] = [
    {"symbol": "SSI", "name": "Chứng khoán SSI",            "ir_url": "https://www.ssi.com.vn/quan-he-nha-dau-tu/bao-cao-tai-chinh"},
    # SHS: trang danh sách dựng bằng JS, nhưng trang chi tiết có URL cố định theo quý → dùng mẫu {q}/{y}
    {"symbol": "SHS", "name": "Chứng khoán Sài Gòn Hà Nội", "ir_url": "https://www.shs.com.vn/cong-bo-thong-tin/shs-cbtt-bao-cao-tai-chinh-quy-{q}-nam-{y}"},
    {"symbol": "VND", "name": "Chứng khoán VNDIRECT",       "ir_url": ""},
    {"symbol": "VCI", "name": "Chứng khoán Vietcap",        "ir_url": ""},
    {"symbol": "HCM", "name": "Chứng khoán TP.HCM",         "ir_url": "https://www.hsc.com.vn/vi/quan-he-nha-dau-tu/bao-cao-tai-chinh"},  # xác minh 13/09/2026
    {"symbol": "MBS", "name": "Chứng khoán MB",             "ir_url": ""},
    {"symbol": "VIX", "name": "Chứng khoán VIX",            "ir_url": ""},
    {"symbol": "VDS", "name": "Chứng khoán Rồng Việt",      "ir_url": ""},
    {"symbol": "BSI", "name": "Chứng khoán BIDV",           "ir_url": ""},
    {"symbol": "FTS", "name": "Chứng khoán FPT",            "ir_url": ""},
    {"symbol": "CTS", "name": "Chứng khoán VietinBank",     "ir_url": ""},
    {"symbol": "TCX", "name": "Chứng khoán Techcombank",    "ir_url": ""},
    {"symbol": "ORS", "name": "Chứng khoán Tiên Phong",     "ir_url": ""},
    {"symbol": "DSE", "name": "Chứng khoán DNSE",           "ir_url": ""},
    {"symbol": "AGR", "name": "Chứng khoán Agribank",       "ir_url": ""},
]


def seed(db) -> int:
    """Thêm 15 công ty mặc định nếu bảng broker còn trống. Trả về số dòng thêm."""
    from .models import Broker

    if db.query(Broker).count():
        return 0
    for b in DEFAULT_BROKERS:
        db.add(Broker(symbol=b["symbol"], name=b["name"], ir_url=b["ir_url"], enabled=True))
    db.commit()
    return len(DEFAULT_BROKERS)


def refresh_universe(db) -> list[dict]:
    """Lấy 50 CTCK niêm yết từ finfo, cập nhật tên/sàn cho broker đã có, trả về toàn bộ universe
    (dùng cho màn 'Thêm công ty')."""
    from common.finfo import broker_universe

    from .models import Broker

    uni = broker_universe()
    by = {u["code"]: u for u in uni}
    for b in db.query(Broker).all():
        u = by.get(b.symbol)
        if u:
            b.name = b.name or u["name"]
            b.floor = u["floor"]
    db.commit()
    return uni

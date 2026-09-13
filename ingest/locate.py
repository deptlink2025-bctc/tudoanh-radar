"""Bước 2 — tìm trang thuyết minh chứa bảng chi tiết tài sản tài chính (FVTPL / AFS / HTM).

PDF là ảnh scan nên không grep được. Gửi thumbnail 60 DPI theo lô 8 trang cho model rẻ
(mặc định claude-haiku-4-5), hỏi câu nhị phân từng trang. Kết quả cache vào report.note_pages
để không tốn lại. Người dùng có thể ghi đè bằng cách gõ số trang trên màn duyệt.

Bảng cần tìm thường nằm ở nửa sau báo cáo (thuyết minh số 5–9), nên quét từ trang 1/3 trở đi
trước; không thấy mới quét phần đầu.
"""
from __future__ import annotations

import json
import logging

from common.config import LOCATE_MODEL

from . import slice as pdfslice
from .claude_client import client

logger = logging.getLogger(__name__)

BATCH = 8

_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer"},
                    "has_table": {"type": "boolean"},
                    "classes": {"type": "array", "items": {"type": "string", "enum": ["FVTPL", "AFS", "HTM"]}},
                    "note": {"type": "string"},
                },
                "required": ["page", "has_table", "classes", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["pages"],
    "additionalProperties": False,
}

_PROMPT = """Đây là các trang scan từ báo cáo tài chính quý của một công ty chứng khoán Việt Nam.
Với TỪNG trang, trả lời: trang này có chứa BẢNG LIỆT KÊ CHI TIẾT các khoản đầu tư tài chính
theo từng mã chứng khoán không? Bảng cần tìm có đặc điểm:
- Nằm trong phần THUYẾT MINH, tiêu đề kiểu "Tài sản tài chính ghi nhận thông qua lãi/lỗ (FVTPL)",
  "Tài sản tài chính sẵn sàng để bán (AFS)", "Đầu tư nắm giữ đến ngày đáo hạn (HTM)",
  "Tình hình biến động giá trị thị trường danh mục tài sản tài chính", "Các khoản đầu tư",
  hoặc "Chứng khoán đầu tư".
- Có cột số lượng và/hoặc giá gốc ("Giá mua") và giá trị hợp lý ("Giá trị thị trường", "Giá trị đánh giá lại").
- Thường có hai nhóm cột: kỳ này (30/06, 30/09...) và đầu năm (01/01).
- Liệt kê từng mã (HPG, VHM, TCB...) hoặc từng loại (cổ phiếu niêm yết, trái phiếu, chứng chỉ tiền gửi).
TUYỆT ĐỐI KHÔNG tính (has_table = false):
- BẢNG CÂN ĐỐI KẾ TOÁN / Statement of financial position: nhận ra bằng cột "Mã số"/"Code",
  "Thuyết minh"/"Note", các dòng đánh số 111, 112, 113, 115, 131..., dù có chữ FVTPL/AFS/HTM.
- Báo cáo kết quả kinh doanh, lưu chuyển tiền tệ, bảng lãi/lỗ từ tài sản tài chính.
- Trang chữ thuần (chính sách kế toán), bảng phân tích rủi ro, bảng chỉ có số tổng.
Bảng cần tìm có tiêu đề kiểu "Các loại tài sản tài chính" / "Types of financial assets" /
"Tài sản tài chính FVTPL" và dòng là TÊN CÔNG CỤ (mã cổ phiếu, "Cổ phiếu niêm yết", "Trái phiếu",
"Chứng chỉ tiền gửi"...) với cột giá gốc ("Giá mua", "Original value") và giá trị hợp lý ("Fair value").
Tài liệu có thể là bản tiếng Anh. Số trang của từng ảnh được ghi ngay trước ảnh. Trả về đúng số trang đó."""


def _ask(pdf: str, pages: list[int]) -> list[dict]:
    content: list[dict] = []
    for p, b64 in pdfslice.thumbnails_b64(pdf, pages):
        content.append({"type": "text", "text": f"[Trang {p}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content.append({"type": "text", "text": _PROMPT})

    resp = client().messages.create(
        model=LOCATE_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["pages"]


def locate(pdf: str, page_count: int) -> list[int]:
    """Trả về danh sách trang (1-based, tăng dần) có bảng chi tiết. Rỗng nếu không thấy."""
    start = max(1, page_count // 3)
    order = list(range(start, page_count + 1)) + list(range(1, start))
    found: list[int] = []
    seen_hit = False
    for i in range(0, len(order), BATCH):
        batch = order[i:i + BATCH]
        try:
            res = _ask(pdf, batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("locate lô %s lỗi: %s", batch, exc)
            continue
        hits = [r["page"] for r in res if r.get("has_table") and r["page"] in batch]
        if hits:
            found.extend(hits)
            seen_hit = True
        elif seen_hit and found:
            # Bảng thuyết minh liền trang; đã thấy rồi mà lô này không có → dừng sớm cho rẻ.
            break
    return sorted(set(found))


def expand(pages: list[int], page_count: int) -> list[int]:
    """Bảng hay tràn sang trang kế: thêm 1 trang sau mỗi trang tìm được (tối đa 6 trang)."""
    out = set(pages)
    for p in pages:
        if p + 1 <= page_count:
            out.add(p + 1)
    return sorted(out)[:6]

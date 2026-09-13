"""Bước 3 — đọc ảnh bảng thuyết minh thành số bằng claude-opus-5.

Gửi PDF con (chỉ các trang đã định vị) dưới dạng block `document` base64 — Claude đọc trực tiếp
trang scan. Ép JSON đúng schema bằng output_config.format. Streaming để tránh timeout khi
bảng dài. Thiếu số thì trả null — KHÔNG đoán; người duyệt sẽ nhập tay.
"""
from __future__ import annotations

import json
import logging
import re

from common.config import EXTRACT_MODEL
from common.quarters import end_date, label

from . import slice as pdfslice
from .claude_client import client

logger = logging.getLogger(__name__)

_ROW = {
    "type": "object",
    "properties": {
        "asset_class": {"type": "string", "enum": ["FVTPL", "AFS", "HTM"]},
        "ticker": {"type": ["string", "null"], "description": "Mã chứng khoán 3 ký tự nếu dòng là một mã cụ thể; null nếu là dòng gộp"},
        "raw_label": {"type": "string", "description": "Nguyên văn tên dòng trong bảng"},
        "kind": {"type": "string", "enum": ["listed_stock", "unlisted_stock", "bond", "fund", "deposit", "group_total", "other"]},
        "quantity": {"type": ["number", "null"]},
        "cost_value": {"type": ["number", "null"], "description": "Giá gốc, VND"},
        "fair_value": {"type": ["number", "null"], "description": "Giá trị hợp lý / giá thị trường, VND"},
        "confidence": {"type": "number", "description": "0–1: 1 nếu đọc rõ, giảm khi ảnh mờ hoặc cột lệch"},
    },
    "required": ["asset_class", "ticker", "raw_label", "kind", "quantity", "cost_value", "fair_value", "confidence"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "unit_multiplier": {"type": "integer", "description": "1 nếu bảng ghi VND; 1000 nếu 'nghìn đồng'; 1000000 nếu 'triệu đồng'"},
        "rows": {"type": "array", "items": _ROW},
        "totals": {
            "type": "array",
            "description": "Các dòng 'Cộng' / 'Tổng' đọc được, để đối chiếu",
            "items": {
                "type": "object",
                "properties": {
                    "asset_class": {"type": "string", "enum": ["FVTPL", "AFS", "HTM"]},
                    "label": {"type": "string"},
                    "cost_value": {"type": ["number", "null"]},
                    "fair_value": {"type": ["number", "null"]},
                },
                "required": ["asset_class", "label", "cost_value", "fair_value"],
                "additionalProperties": False,
            },
        },
        "source_pages": {"type": "array", "items": {"type": "integer"},
                         "description": "Số thứ tự (1-based, theo thứ tự trang trong tài liệu gửi kèm) của các trang chứa bảng đã bóc"},
        "notes": {"type": "string", "description": "Ghi chú ngắn cho người duyệt: cột nào thiếu, chỗ nào mờ"},
    },
    "required": ["unit_multiplier", "rows", "totals", "source_pages", "notes"],
    "additionalProperties": False,
}


def _prompt(symbol: str, quarter: str) -> str:
    return f"""Đây là (các trang của) báo cáo tài chính riêng {label(quarter)} (kỳ kết thúc {end_date(quarter):%d/%m/%Y})
của công ty chứng khoán {symbol}, dạng ảnh scan, có thể là bản tiếng Việt hoặc tiếng Anh.
Tìm trong phần THUYẾT MINH bảng chi tiết tài sản tài chính FVTPL, AFS và HTM ("Các loại tài sản
tài chính" / "Types of financial assets" / "Tình hình biến động giá trị thị trường danh mục") và
bóc TOÀN BỘ các dòng thành dữ liệu có cấu trúc. KHÔNG lấy số từ Bảng cân đối kế toán (trang có
cột Mã số 112/113/115) — đó chỉ là số tổng, đưa vào totals nếu muốn đối chiếu.

Quy tắc bắt buộc:
1. Chỉ lấy số của CỘT KỲ NÀY ({end_date(quarter):%d/%m/%Y}), KHÔNG lấy cột đầu năm / kỳ trước.
2. Số kiểu Việt Nam: dấu chấm phân cách nghìn (742.280.000.000), dấu phẩy là thập phân.
   Số trong ngoặc đơn là số âm. Đơn vị mặc định VND; nếu bảng ghi "nghìn đồng"/"triệu đồng"
   thì ghi vào unit_multiplier và GIỮ số như trong bảng (không tự nhân).
3. Mỗi mã chứng khoán là MỘT dòng, ticker = mã 3 ký tự in hoa (HPG, VHM...).
   Dòng nhóm CÓ các dòng con liệt kê bên dưới (VD "Cổ phiếu" rồi tới CTG, HPG, "Cổ phiếu khác")
   là TỔNG PHỤ → đưa vào totals với label, KHÔNG đưa vào rows (nếu không sẽ đếm hai lần).
   Dòng nhóm KHÔNG có dòng con (VD "Trái phiếu", "Chứng chỉ quỹ", "Cổ phiếu khác") → là một row
   với ticker = null và kind tương ứng — đây là phần không nêu tên mã, cần giữ để tổng khớp.
   Dòng "Cộng"/"Tổng"/tên nhóm FVTPL, AFS, HTM có số → totals.
4. Ô trống, gạch ngang, hoặc mờ không đọc được → null. TUYỆT ĐỐI KHÔNG suy đoán số.
5. raw_label giữ nguyên văn (kể cả lỗi chính tả) để người duyệt đối chiếu với ảnh.
6. confidence: 1.0 nếu đọc rõ; giảm khi ảnh mờ, số bị che, hoặc cột bị lệch hàng.
7. source_pages: số thứ tự các trang (đếm từ 1 theo thứ tự trong tài liệu gửi kèm) chứa bảng đã bóc.
8. Ghi vào notes: bảng nào thiếu cột số lượng, cột nào chỉ có giá trị hợp lý, chỗ nào nghi ngờ."""


def extract(pdf: str, pages: list[int] | None, symbol: str, quarter: str) -> dict:
    """Trả về dict theo _SCHEMA. pages=None → gửi TOÀN BỘ tài liệu (nén nhỏ) — dùng khi không định
    vị được trang. Ném lỗi API ra ngoài để pipeline đánh dấu stuck."""
    b64 = pdfslice.slice_b64(pdf, pages) if pages else pdfslice.compact_b64(pdf)
    with client().messages.stream(
        model=EXTRACT_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        # effort medium: đây là việc CHÉP SỐ từ ảnh, không phải suy luận; high tốn gấp đôi token ra mà
        # không đọc đúng hơn (đo trên 11 báo cáo Q2/2026). 4 kiểm tra đối chiếu mới là lưới an toàn.
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": _prompt(symbol, quarter)},
            ],
        }],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("Model từ chối đọc tài liệu này")
    text = next(b.text for b in msg.content if b.type == "text")
    data = json.loads(text)
    data["_usage"] = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}
    return data


_TICKER_RE = re.compile(r"^[A-Z]{3}$")


def normalize(data: dict) -> list[dict]:
    """JSON từ model → danh sách dòng holding chuẩn (VND, ticker in hoa, kind → is_listed sơ bộ)."""
    mult = int(data.get("unit_multiplier") or 1)
    out: list[dict] = []
    for r in data.get("rows") or []:
        t = (r.get("ticker") or "").strip().upper() or None
        if t and not _TICKER_RE.match(t):
            # "TCB2426", "VIC12103" là trái phiếu — giữ nguyên mã, đánh dấu không niêm yết
            r["kind"] = "bond" if r.get("kind") == "listed_stock" else r.get("kind")
        def v(x):
            return None if x is None else float(x) * mult
        out.append({
            "asset_class": r["asset_class"],
            "ticker": t or "",
            "raw_label": r.get("raw_label") or "",
            "kind": r.get("kind") or "other",
            "quantity": None if r.get("quantity") is None else float(r["quantity"]),
            "cost_value": v(r.get("cost_value")),
            "fair_value": v(r.get("fair_value")),
            "confidence": float(r.get("confidence") or 0),
        })
    return out

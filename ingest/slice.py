"""PyMuPDF: đếm trang, render thumbnail/ảnh trang, cắt trang thuyết minh ra PDF con.

PDF con là BẮT BUỘC: giới hạn request Messages API là 32 MB, còn SHS Q2/2026 nặng 37,8 MB.
Ba trang thuyết minh cắt ra thường < 2 MB.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pymupdf

from common.config import PAGES_DIR

MAX_SLICE_BYTES = 30 * 1024 * 1024


def page_count(pdf: str | Path) -> int:
    with pymupdf.open(pdf) as doc:
        return doc.page_count


def has_text_layer(pdf: str | Path) -> bool:
    """Đa số BCTC CTCK là scan (không text). Ghi nhận để hiển thị, không đổi cách xử lý."""
    with pymupdf.open(pdf) as doc:
        for i in range(min(doc.page_count, 5)):
            if doc[i].get_text().strip():
                return True
    return False


def render_page_png(pdf: str | Path, page_no: int, dpi: int = 110) -> bytes:
    """page_no 1-based. Dùng cho thumbnail (định vị) và ảnh gốc trên màn duyệt."""
    with pymupdf.open(pdf) as doc:
        pix = doc[page_no - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return pix.tobytes("png")


def cache_page_png(pdf: str | Path, symbol: str, quarter: str, page_no: int, dpi: int = 110) -> Path:
    out = PAGES_DIR / f"{symbol}_{quarter}" / f"p{page_no:03d}_{dpi}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(render_page_png(pdf, page_no, dpi))
    return out


def slice_pages(pdf: str | Path, pages: list[int]) -> bytes:
    """Cắt các trang (1-based) thành một PDF mới, trả về bytes."""
    with pymupdf.open(pdf) as src, pymupdf.open() as out:
        for p in pages:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        data = out.tobytes(garbage=3, deflate=True)
    if len(data) > MAX_SLICE_BYTES:
        raise ValueError(f"PDF con {len(data) / 1e6:.1f} MB vẫn quá 30 MB — giảm số trang")
    return data


def slice_b64(pdf: str | Path, pages: list[int]) -> str:
    return base64.standard_b64encode(slice_pages(pdf, pages)).decode("ascii")


def thumbnails_b64(pdf: str | Path, pages: list[int], dpi: int = 60) -> list[tuple[int, str]]:
    """[(page_no, png_base64)] ảnh nhỏ để model tìm trang. 60 DPI đủ đọc tiêu đề bảng."""
    out = []
    with pymupdf.open(pdf) as doc:
        for p in pages:
            pix = doc[p - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            out.append((p, base64.standard_b64encode(pix.tobytes("png")).decode("ascii")))
    return out

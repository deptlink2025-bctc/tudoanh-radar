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


def _sideways(pix: pymupdf.Pixmap) -> bool:
    """Chữ đang nằm ngang? Heuristic không cần OCR: dòng chữ tạo vân đậm/nhạt đều theo một trục.
    Với chữ thẳng, tổng mực theo TỪNG HÀNG dao động mạnh (dòng chữ / khoảng trắng xen kẽ); với chữ
    nằm ngang thì tổng theo TỪNG CỘT dao động mạnh hơn. So phương sai hai chiều.
    Scan BCTC hay có trang landscape xoay 90° mà cờ /Rotate không sửa được (AGR trang 39, SHS 3–24)."""
    w, h = pix.width, pix.height
    buf = pix.samples  # grayscale, 1 byte/pixel
    step = max(1, min(w, h) // 300)   # lấy mẫu cho nhanh
    rows = [sum(255 - buf[y * w + x] for x in range(0, w, step)) for y in range(0, h, step)]
    cols = [sum(255 - buf[y * w + x] for y in range(0, h, step)) for x in range(0, w, step)]

    def var(v):
        m = sum(v) / len(v)
        return sum((a - m) ** 2 for a in v) / len(v) / (m * m + 1e-9)   # chuẩn hoá theo mực trung bình

    return var(cols) > var(rows) * 1.3


def upright_pixmap(page: pymupdf.Page, dpi: int) -> tuple[pymupdf.Pixmap, int]:
    """Render trang; nếu chữ nằm ngang thì xoay thêm 90°. Trả về (pixmap, góc đã xoay thêm)."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    if _sideways(pix):
        mat = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(90)
        return page.get_pixmap(matrix=mat, colorspace=pymupdf.csGRAY), 90
    return pix, 0


def render_page_png(pdf: str | Path, page_no: int, dpi: int = 110) -> bytes:
    """page_no 1-based. Dùng cho thumbnail (định vị) và ảnh gốc trên màn duyệt. Đã dựng thẳng."""
    with pymupdf.open(pdf) as doc:
        pix, _ = upright_pixmap(doc[page_no - 1], dpi)
        return pix.tobytes("png")


def cache_page_png(pdf: str | Path, symbol: str, quarter: str, page_no: int, dpi: int = 110) -> Path:
    out = PAGES_DIR / f"{symbol}_{quarter}" / f"p{page_no:03d}_{dpi}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(render_page_png(pdf, page_no, dpi))
    return out


def slice_pages(pdf: str | Path, pages: list[int]) -> bytes:
    """Cắt các trang (1-based) thành một PDF mới đã dựng thẳng, trả về bytes.

    Dựng thẳng bằng cách rasterize lại ở 150 DPI (trang scan vốn là ảnh nên không mất gì),
    đồng thời nén JPEG để chắc chắn dưới 32 MB."""
    return _raster_pdf(pdf, pages, dpi=150, quality=70)


def compact_pdf(pdf: str | Path, dpi: int = 90, quality: int = 55) -> bytes:
    """TOÀN BỘ tài liệu, ảnh nhỏ — dùng khi không định vị được trang thuyết minh.
    58 trang ở 90 DPI JPEG ≈ 4–6 MB, Opus đọc được cả cuốn trong một lần."""
    with pymupdf.open(pdf) as doc:
        n = doc.page_count
    return _raster_pdf(pdf, list(range(1, n + 1)), dpi=dpi, quality=quality)


def _raster_pdf(pdf: str | Path, pages: list[int], dpi: int, quality: int) -> bytes:
    with pymupdf.open(pdf) as src, pymupdf.open() as out:
        for p in pages:
            pix, _ = upright_pixmap(src[p - 1], dpi)
            img = pix.tobytes("jpeg", jpg_quality=quality)
            w, h = pix.width * 72 / dpi, pix.height * 72 / dpi
            page = out.new_page(width=w, height=h)
            page.insert_image(page.rect, stream=img)
        data = out.tobytes(garbage=3, deflate=True)
    if len(data) > MAX_SLICE_BYTES:
        if dpi > 60:
            return _raster_pdf(pdf, pages, dpi=int(dpi * 0.7), quality=max(35, quality - 10))
        raise ValueError(f"PDF con {len(data) / 1e6:.1f} MB vẫn quá 30 MB — giảm số trang")
    return data


def slice_b64(pdf: str | Path, pages: list[int]) -> str:
    return base64.standard_b64encode(slice_pages(pdf, pages)).decode("ascii")


def compact_b64(pdf: str | Path) -> str:
    return base64.standard_b64encode(compact_pdf(pdf)).decode("ascii")


def thumbnails_b64(pdf: str | Path, pages: list[int], dpi: int = 72) -> list[tuple[int, str]]:
    """[(page_no, png_base64)] ảnh nhỏ đã dựng thẳng để model tìm trang."""
    out = []
    with pymupdf.open(pdf) as doc:
        for p in pages:
            pix, _ = upright_pixmap(doc[p - 1], dpi)
            out.append((p, base64.standard_b64encode(pix.tobytes("png")).decode("ascii")))
    return out

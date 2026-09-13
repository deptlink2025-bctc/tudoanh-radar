"""Đóng dấu phiên bản vào docs/index.html: app.js?v=<băm nội dung>, styles.css?v=…

GitHub Pages cache 10 phút và app đã cài trên điện thoại giữ file cũ lâu hơn nữa (bài học KingStock:
điện thoại giữ index.html cũ rồi gọi app.js đã đổi). Đổi tên tham số ?v= mỗi khi nội dung đổi
thì trình duyệt buộc phải tải lại. Chạy tự động trong export.write() và có thể chạy tay:
    venv\\Scripts\\python -m ingest.stamp
"""
from __future__ import annotations

import hashlib
import re

from common.config import ROOT

DOCS = ROOT / "docs"
FILES = ["app.js", "styles.css", "config.js", "sw.js"]


def _h(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def stamp() -> dict[str, str]:
    idx = DOCS / "index.html"
    html = idx.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for f in FILES:
        p = DOCS / f
        if not p.exists():
            continue
        v = _h(p)
        out[f] = v
        html = re.sub(rf'(["\'(]){re.escape(f)}(\?v=[0-9a-f]+)?(["\')])', rf"\g<1>{f}?v={v}\g<3>", html)
    # sw.js được đăng ký trong app.js → cũng đóng dấu ở đó để trình duyệt kiểm tra SW mới
    app = DOCS / "app.js"
    if app.exists() and "sw.js" in out:
        s = app.read_text(encoding="utf-8")
        s2 = re.sub(r'register\("sw\.js(\?v=[0-9a-f]+)?"\)', f'register("sw.js?v={out["sw.js"]}")', s)
        if s2 != s:
            app.write_text(s2, encoding="utf-8")
            out["app.js"] = _h(app)
            html = re.sub(r'(["\'(])app\.js(\?v=[0-9a-f]+)?(["\')])', rf"\g<1>app.js?v={out['app.js']}\g<3>", html)
    idx.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(stamp())

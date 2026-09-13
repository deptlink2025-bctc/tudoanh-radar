"""SQLite local cho Tầng A. Ba bảng: broker → report → holding.

Mọi cột thời gian dùng giờ VN naive (không func.now() — SQLite trả UTC, lệch 7 giờ).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from common.config import TZ


def now_vn() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


class Broker(Base):
    __tablename__ = "broker"
    symbol: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    floor: Mapped[str] = mapped_column(String(8), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ir_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now_vn)


# Thứ tự bước trong pipeline. 'stuck' có thể xảy ra ở bất kỳ bước nào.
STATUSES = ["queued", "fetching", "locating", "extracting", "validating", "review", "approved", "stuck"]
STEP_INDEX = {"queued": 0, "fetching": 1, "locating": 2, "extracting": 3, "validating": 4, "review": 5, "approved": 5, "stuck": -1}


class Report(Base):
    __tablename__ = "report"
    __table_args__ = (UniqueConstraint("broker", "quarter", "stmt_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker: Mapped[str] = mapped_column(ForeignKey("broker.symbol"))
    quarter: Mapped[str] = mapped_column(String(8))              # '2026Q2'
    stmt_type: Mapped[str] = mapped_column(String(12), default="rieng")   # 'rieng' | 'hop_nhat'
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stuck_step: Mapped[str] = mapped_column(String(16), default="")   # bước bị kẹt
    stuck_reason: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str] = mapped_column(Text, default="")
    pdf_sha256: Mapped[str] = mapped_column(String(64), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    note_pages: Mapped[str] = mapped_column(String(64), default="")   # '42,43,44' (1-based)
    model_used: Mapped[str] = mapped_column(String(64), default="")
    checks_json: Mapped[str] = mapped_column(Text, default="")        # kết quả 4 kiểm tra
    finfo_json: Mapped[str] = mapped_column(Text, default="")         # số tổng đối chiếu
    extracted_at: Mapped[datetime | None] = mapped_column(default=None)
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=now_vn, onupdate=now_vn)

    holdings: Mapped[list["Holding"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class Holding(Base):
    __tablename__ = "holding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id"))
    asset_class: Mapped[str] = mapped_column(String(8))       # FVTPL | AFS | HTM
    ticker: Mapped[str] = mapped_column(String(16))
    raw_label: Mapped[str] = mapped_column(Text, default="")
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)
    quantity: Mapped[float | None] = mapped_column(Float, default=None)
    quantity_source: Mapped[str] = mapped_column(String(10), default="disclosed")  # disclosed|implied|manual
    cost_value: Mapped[float | None] = mapped_column(Float, default=None)          # VND
    cost_source: Mapped[str] = mapped_column(String(10), default="disclosed")
    fair_value: Mapped[float | None] = mapped_column(Float, default=None)          # VND
    fair_source: Mapped[str] = mapped_column(String(10), default="disclosed")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    flags: Mapped[str] = mapped_column(Text, default="")      # 'qty_price_mismatch;unlisted'
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)   # người duyệt bỏ dòng

    report: Mapped[Report] = relationship(back_populates="holdings")

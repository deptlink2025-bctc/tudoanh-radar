"""Chỉ báo cáo approved mới được xuất; nhãn nguồn và dòng đã bỏ được xử lý đúng."""
import json
import os
from pathlib import Path

from ingest import export
from ingest.db import init_db, session
from ingest.models import Broker, Holding, Report


def setup_module(module):
    p = Path(os.environ["INGEST_DB"])
    if p.exists():
        p.unlink()
    init_db()


def test_export_only_approved(tmp_path, monkeypatch):
    db = session()
    db.add(Broker(symbol="AAA", name="Test", floor="HOSE"))
    ok = Report(broker="AAA", quarter="2026Q2", status="approved")
    ok.holdings = [
        Holding(asset_class="FVTPL", ticker="HPG", is_listed=True, quantity=10, quantity_source="manual", cost_value=1e9, fair_value=2e9),
        Holding(asset_class="FVTPL", ticker="XXX", is_listed=True, quantity=1, deleted=True, cost_value=1, fair_value=1),
    ]
    draft = Report(broker="AAA", quarter="2026Q1", status="review")
    draft.holdings = [Holding(asset_class="FVTPL", ticker="VHM", is_listed=True, quantity=5, cost_value=1, fair_value=1)]
    db.add_all([ok, draft])
    db.commit()
    db.close()

    monkeypatch.setattr(export, "OUT", tmp_path / "holdings.json")
    d = export.write()
    assert [r["quarter"] for r in d["reports"]] == ["2026Q2"]
    hs = d["reports"][0]["holdings"]
    assert len(hs) == 1 and hs[0]["quantity_source"] == "manual"
    assert json.loads((tmp_path / "holdings.json").read_text(encoding="utf-8"))["brokers"][0]["symbol"] == "AAA"

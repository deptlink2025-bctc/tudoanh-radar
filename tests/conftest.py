import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# DB tạm cho test — không đụng ingest.db thật
os.environ.setdefault("INGEST_DB", str(ROOT / "tests" / ".test_ingest.db"))

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    """Demo SQLite sources + a config pointing at them, built fresh for the test session."""
    import subprocess
    d = tmp_path_factory.mktemp("demo")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo_data.py"), str(d / "data")], check=True)
    (d / "specs").mkdir()
    (d / "specs" / "catalog.json").write_text((ROOT / "specs" / "catalog.json").read_text(), encoding="utf-8")
    cfg = (ROOT / "config.yaml").read_text(encoding="utf-8").replace("audit_log: audit.jsonl", "audit_log: null")
    (d / "config.yaml").write_text(cfg, encoding="utf-8")
    return d

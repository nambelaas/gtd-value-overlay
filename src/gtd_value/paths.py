from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]     # folder repo
DATA_DIR = ROOT / "data"
TEMPLATE_DIR = ROOT / "templates"
UPDATES_DIR = ROOT / "updates"
DOCS_DIR = ROOT / "docs"
VALUES_FILE = DATA_DIR / "values.json"
ARROW_FILE = DATA_DIR / "arrow.png"
LOG_DIR = ROOT / "logs"
RUN_DIR = ROOT / ".run"
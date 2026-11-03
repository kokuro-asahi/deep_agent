import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--auth-postgres", action="store_true", default=False,
        help="Test auth SQL against the configured PostgreSQL using an isolated temporary schema.",
    )

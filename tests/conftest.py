import sys
from pathlib import Path

# Tests import the same helpers the pipeline uses from src/, ml/ and mis/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "mis"))

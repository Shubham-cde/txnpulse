import sys
from pathlib import Path

# Tests import the same helpers the pipeline uses from src/ and ml/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ml"))

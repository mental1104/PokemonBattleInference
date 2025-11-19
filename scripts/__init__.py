from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw"
CONFIG_PATH = RAW_DATA_PATH / "config"

__all__ = ["CONFIG_PATH", "RAW_DATA_PATH", "PROJECT_ROOT"]

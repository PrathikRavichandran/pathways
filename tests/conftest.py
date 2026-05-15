import sys
from pathlib import Path

# Add repo root to sys.path so `pathways.*` and `mcp_servers/*` are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

"""Hidden, killable extraction helper. No app/model initialization."""
from pathlib import Path
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.path[:] = [str(root)] + [p for p in sys.path if p != str(Path(__file__).parent)]
    from addons.rag_context.extraction import extract_snapshot
    from addons.rag_context.packages import atomic_json
    try:
        atomic_json(Path(sys.argv[2]), {"ok": True, "snapshot": extract_snapshot(Path(sys.argv[1]), cancelled=lambda: False)})
    except Exception as exc:
        atomic_json(Path(sys.argv[2]), {"ok": False, "error": str(exc)[:1000]})
        sys.exit(1)

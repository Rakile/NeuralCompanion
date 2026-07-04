import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import long_term_memory


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "memory.sqlite3"
        long_term_memory.init_store(db_path)
        model_a = long_term_memory.embedding_model_key("model-a", 8192)
        model_b = long_term_memory.embedding_model_key("model-b", 8192)
        long_term_memory.upsert_embedding(
            target_kind="record",
            target_id="rec_1",
            model=model_a,
            text="alpha",
            vector=[1.0, 0.0],
            path=db_path,
        )
        long_term_memory.upsert_embedding(
            target_kind="record",
            target_id="rec_1",
            model=model_b,
            text="alpha",
            vector=[0.0, 1.0],
            path=db_path,
        )

        deleted = long_term_memory.delete_embeddings(model=model_a, path=db_path)

        status_a = long_term_memory.embedding_status(model=model_a, path=db_path)
        status_b = long_term_memory.embedding_status(model=model_b, path=db_path)
        assert deleted == 1, deleted
        assert status_a["model_embeddings"] == 0, status_a
        assert status_b["model_embeddings"] == 1, status_b

        cleared = long_term_memory.delete_all_embeddings(path=db_path)
        status_b = long_term_memory.embedding_status(model=model_b, path=db_path)
        assert cleared == 1, cleared
        assert status_b["model_embeddings"] == 0, status_b
    print("long_term_memory embedding model guard smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

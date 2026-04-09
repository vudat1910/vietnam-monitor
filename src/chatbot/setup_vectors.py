import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from langchain_huggingface import HuggingFaceEmbeddings

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres"
}

EMBED_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 50

def setup_vector():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("""
        ALTER TABLE re_listings
        ADD COLUMN IF NOT EXISTS embedding vector(384);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_re_embedding
        ON re_listings USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=64);
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("[setup] PGVECTOR ok — vector(384)")

def embed_listings():
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, description, address, district, city, category
        FROM re_listings
        WHERE embedding IS NULL AND is_active=TRUE
    """)
    rows = cur.fetchall()

    if not rows:
        print("[embed] Không có listing nào cần embed.")
        cur.close()
        conn.close()
        return

    total = len(rows)
    print(f"[embed] Bắt đầu embed {total} listings...")

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        texts = []
        for r in batch:
            parts = [
                r.get("title", ""),
                r.get("category", ""),
                r.get("city", ""),
                r.get("district", ""),
                r.get("address", ""),
                (r.get("description") or "")[:500],
            ]
            texts.append(" | ".join(filter(None, parts)))

        vecs = embeddings.embed_documents(texts)

        for row, vec in zip(batch, vecs):
            vec_str = "[" + ", ".join(map(str, vec)) + "]"
            cur.execute(
                "UPDATE re_listings SET embedding = %s::vector WHERE id = %s",
                (vec_str, row["id"])
            )
        conn.commit()
        done = min(i + BATCH_SIZE, total)
        print(f"[embed] {done}/{total}")

    cur.close()
    conn.close()
    print(f"[embed] Hoàn thành embed {total} listings.")

if __name__ == "__main__":
    setup_vector()
    embed_listings()

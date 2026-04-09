import psycopg2
from psycopg2.extras import RealDictCursor

DB_config = {
    "host":     "127.0.0.1",
    "port":     5432,
    "dbname":   "postgres",
    "user":     "postgres",
}

def get_conn():
    return psycopg2.connect(**DB_config, cursor_factory=RealDictCursor)
def init_db():
    sql = """
    CREATE TABLE IF NOT EXISTS re_listings (
        id              SERIAL PRIMARY KEY,
        source          VARCHAR(50),
        external_id     VARCHAR(255),
        listing_tier    VARCHAR(50),
        title           TEXT,
        description     TEXT,
        price           BIGINT,
        price_text      VARCHAR(100),
        price_per_m2    BIGINT,
        area            FLOAT,
        address         TEXT,
        ward            VARCHAR(100),
        district        VARCHAR(100),
        city            VARCHAR(50),
        listing_type    VARCHAR(20),
        category        VARCHAR(30),
        bedrooms        INTEGER,
        bathrooms       INTEGER,
        floor           INTEGER,
        total_floors    INTEGER,
        direction       VARCHAR(30),
        balcony_dir     VARCHAR(30),
        legal           VARCHAR(100),
        furniture       VARCHAR(50),
        project_name    VARCHAR(200),
        developer       VARCHAR(200),
        contact_name    VARCHAR(150),
        contact_phone   VARCHAR(30),
        images_json     TEXT,
        source_url      TEXT UNIQUE,
        posted_at       TIMESTAMP,
        expires_at      TIMESTAMP,
        is_active       BOOLEAN DEFAULT TRUE,
        scraped_at      TIMESTAMP DEFAULT NOW(),
        updated_at      TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_re_city      ON re_listings(city);
    CREATE INDEX IF NOT EXISTS ix_re_district  ON re_listings(district);
    CREATE INDEX IF NOT EXISTS ix_re_type      ON re_listings(listing_type);
    CREATE INDEX IF NOT EXISTS ix_re_category  ON re_listings(category);
    CREATE INDEX IF NOT EXISTS ix_re_price     ON re_listings(price);
    CREATE INDEX IF NOT EXISTS ix_re_area      ON re_listings(area);
    CREATE INDEX IF NOT EXISTS ix_re_project   ON re_listings(project_name);
    CREATE INDEX IF NOT EXISTS ix_re_source    ON re_listings(source);
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()
    print("[RE-DB] Tables ready.")

if __name__ == "__main__":
    init_db()
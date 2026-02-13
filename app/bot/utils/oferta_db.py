import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent.parent / "oferta.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oferta_accepted (
            telegram_id INTEGER PRIMARY KEY,
            accepted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_oferta_accepted(telegram_id: int) -> bool:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    result = conn.execute(
        "SELECT 1 FROM oferta_accepted WHERE telegram_id = ?", 
        (telegram_id,)
    ).fetchone()
    conn.close()
    return result is not None

def accept_oferta(telegram_id: int):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO oferta_accepted (telegram_id) VALUES (?)",
        (telegram_id,)
    )
    conn.commit()
    conn.close()


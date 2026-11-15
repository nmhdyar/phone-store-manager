from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "phone_store.db"
JSON_PATH = BASE_DIR.parent / "phonestore" / "phones.json"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _record_activity(connection, action, details):
    connection.execute(
        "INSERT INTO activity_log (action, details) VALUES (?, ?)",
        (action, details),
    )


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS phones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                price REAL NOT NULL CHECK(price > 0),
                quantity INTEGER NOT NULL CHECK(quantity >= 0)
            )
        """)

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(phones)").fetchall()
        }
        if "cost_price" not in columns:
            connection.execute(
                "ALTER TABLE phones ADD COLUMN cost_price REAL NOT NULL DEFAULT 0 "
                "CHECK(cost_price >= 0)"
            )
        if "cost_known" not in columns:
            connection.execute(
                "ALTER TABLE phones ADD COLUMN cost_known INTEGER NOT NULL DEFAULT 0 "
                "CHECK(cost_known IN (0, 1))"
            )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_id INTEGER REFERENCES phones(id) ON DELETE SET NULL,
                phone_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL CHECK(unit_price > 0),
                unit_cost REAL NOT NULL DEFAULT 0 CHECK(unit_cost >= 0),
                total REAL NOT NULL,
                profit REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('low_stock_limit', '5')"
        )

        count = connection.execute("SELECT COUNT(*) FROM phones").fetchone()[0]
        if count == 0:
            if JSON_PATH.exists():
                try:
                    imported = json.loads(JSON_PATH.read_text(encoding="utf-8"))
                    if not isinstance(imported, list):
                        raise ValueError("Legacy JSON must contain a list.")
                    for item in imported:
                        name = str(item["name"]).strip()
                        price = float(item["price"])
                        quantity = int(item["quantity"])
                        if name and price > 0 and quantity >= 0:
                            connection.execute(
                                "INSERT OR IGNORE INTO phones(name, price, quantity) VALUES (?, ?, ?)",
                                (name, price, quantity),
                            )
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    # Preserve the existing database and do not silently seed over bad legacy data.
                    pass
            else:
                connection.executemany(
                    "INSERT INTO phones(name, price, quantity) VALUES (?, ?, ?)",
                    [
                        ("Samsung", 1500, 6),
                        ("IPhone", 2000, 10),
                        ("Xiaomi", 800, 3),
                    ],
                )

        connection.execute("CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at DESC)")

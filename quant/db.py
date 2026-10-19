"""SQLite veri deposu (data/tefas.sqlite).

Depo git'e girmez; GitHub Actions'ta çalıştırmalar arasında cache ile taşınır.
Yalnızca son HISTORY_YEARS yılın günlük kayıtları tutulur.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "tefas.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    price REAL NOT NULL,
    shares REAL,
    investors INTEGER,
    size REAL,
    PRIMARY KEY (code, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS funds (
    code TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    category_src TEXT,
    fee REAL,
    stopaj REAL,
    trading_active INTEGER,
    is_serbest INTEGER,
    fvt_updated TEXT
);

-- Her günün skor fotoğrafı: ileride gerçek (point-in-time) backtest için.
CREATE TABLE IF NOT EXISTS scores (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    score REAL,
    signal TEXT,
    category TEXT,
    PRIMARY KEY (date, code)
) WITHOUT ROWID;

-- Bireysel emeklilik (BES / EMK) fonları: yatırım fonlarından ayrı tutulur.
CREATE TABLE IF NOT EXISTS bes_prices (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    price REAL NOT NULL,
    shares REAL,
    investors INTEGER,
    size REAL,
    PRIMARY KEY (code, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bes_funds (code TEXT PRIMARY KEY, name TEXT);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices (date);
"""


def open_db(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

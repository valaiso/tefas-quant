from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///database/fonlar.db")

with engine.connect() as conn:
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS funds (
        id INTEGER PRIMARY KEY,
        code TEXT,
        name TEXT,
        category TEXT,
        risk_level INTEGER
    )
    """))

    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY,
        code TEXT,
        date TEXT,
        price REAL
    )
    """))

    conn.commit()

print("Fon tabloları oluşturuldu")
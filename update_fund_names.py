import sqlite3
import json

DB = "tefas.db"
JSON_FILE = "funds.json"

conn = sqlite3.connect(DB)
cur = conn.cursor()

with open(JSON_FILE, "r", encoding="utf-8") as f:
    funds = json.load(f)

updated = 0

for fund in funds:
    code = fund["code"]
    name = fund["name"]
    founder = fund["founder"]

    cur.execute("""
        UPDATE funds
        SET name = ?,
            title = ?,
            manager = ?
        WHERE code = ?
    """,
    (
        name,
        name,
        founder,
        code
    ))

    if cur.rowcount > 0:
        updated += 1

conn.commit()

print("Güncellenen fon:", updated)

print(
    cur.execute(
        "SELECT code,name,manager FROM funds LIMIT 5"
    ).fetchall()
)

conn.close()
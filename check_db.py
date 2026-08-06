import sqlite3

DB = "tefas.db"

conn = sqlite3.connect(DB)
cursor = conn.cursor()

print("\nTABLES:\n")

tables = cursor.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()

for t in tables:
    print(t[0])

print("\nCOLUMNS:\n")

for table in [x[0] for x in tables]:
    print("\n---", table, "---")
    try:
        cols = cursor.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        for c in cols:
            print(c[1], c[2])

    except Exception as e:
        print(e)

conn.close()
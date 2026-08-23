import sqlite3
from scoring import detect_qualified_fund

conn = sqlite3.connect("tefas.db")
cur = conn.cursor()
cur.execute("SELECT id, title, category FROM funds")
rows = cur.fetchall()

updated = 0
for fid, title, category in rows:
    qualified = detect_qualified_fund(title, category or "")
    cur.execute("UPDATE funds SET is_qualified=? WHERE id=?", (qualified, fid))
    if cur.rowcount:
        updated += 1

conn.commit()
conn.close()
print(f"{updated} fonun is_qualified alanı güncellendi.")

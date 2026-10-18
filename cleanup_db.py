"""tefas.db veri temizliği (tek seferlik).

- fund_daily_prices: tekrarlı (fund_id, date) satırlarını ve 0/negatif fiyatları siler,
  tekrar oluşmaması için UNIQUE index ekler.
- fund_scores: scoring.py'nin tarihi 1260 gün geriye kaydırdığı dönemde yazdığı
  look-ahead skorlarını siler (bu skorlar o tarihte bilinemeyecek verilerle üretildi).
- funds.is_qualified: "ÖZEL SEKTÖR BORÇLANMA" fonlarını nitelikli sayan hatayı düzeltir.

Çalıştırmadan önce tefas.db'nin yedeğini tefas.db.bak olarak alır.

Kullanım: python cleanup_db.py [--lookahead-date 2023-03-20]
"""
import argparse
import shutil
import sqlite3

from scoring import detect_qualified_fund

DB = "tefas.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookahead-date", default="2023-03-20")
    args = parser.parse_args()

    shutil.copyfile(DB, DB + ".bak")
    print(f"Yedek alındı: {DB}.bak")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("DELETE FROM fund_daily_prices WHERE price IS NULL OR price <= 0")
    print("Silinen 0/boş fiyat:", cur.rowcount)

    cur.execute(
        "DELETE FROM fund_daily_prices WHERE id NOT IN"
        " (SELECT MAX(id) FROM fund_daily_prices GROUP BY fund_id, date)"
    )
    print("Silinen tekrarlı fiyat satırı:", cur.rowcount)

    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fund_daily_prices_fund_date"
        " ON fund_daily_prices (fund_id, date)"
    )

    cur.execute("DELETE FROM fund_scores WHERE date = ?", (args.lookahead_date,))
    print(f"Silinen look-ahead skor ({args.lookahead_date}):", cur.rowcount)

    changed = 0
    for fid, title, category, old in cur.execute(
        "SELECT id, title, category, is_qualified FROM funds"
    ).fetchall():
        new = detect_qualified_fund(title, category or "")
        if old != new:
            cur.execute("UPDATE funds SET is_qualified=? WHERE id=?", (new, fid))
            changed += 1
    print("is_qualified düzeltilen fon:", changed)

    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    print("Bitti.")


if __name__ == "__main__":
    main()

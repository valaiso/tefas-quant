import sqlite3

conn = sqlite3.connect("tefas.db")
c = conn.cursor()

updates = {
    "Yabancı Hisse Senedi": [
        "YABANCI HİSSE",
        "YABANCI HISSE",
        "YABANCI TEKNOLOJİ",
        "YABANCI TEKNOLOJI",
        "YABANCI SAĞLIK",
        "YABANCI SAGLIK",
    ],
    "Hisse Senedi": [
        "HİSSE SENEDİ",
        "HISSE SENEDI",
        "HİSSE",
        "HISSE"
    ],
    "Para Piyasası": [
        "PARA PİYASASI"
    ],
    "Borçlanma": [
        "BORÇLANMA",
        "BORCLANMA"
    ],
    "Altın": [
        "ALTIN"
    ],
    "Değişken": [
        "DEĞİŞKEN",
        "DEGISKEN"
    ],
    "Fon Sepeti": [
        "FON SEPETİ",
        "FON SEPETI",
        "BYF FON SEPETİ",
        "BYF FON SEPETI"
    ],
    "Katılım": [
        "KATILIM"
    ]
}

for category, keys in updates.items():
    for key in keys:
        c.execute(
            """
            UPDATE funds
            SET category=?
            WHERE UPPER(name) LIKE ?
            """,
            (category, f"%{key}%")
        )

# Öncelikli yabancı fon düzeltmesi
c.execute("""
UPDATE funds
SET category='Yabancı Hisse Senedi'
WHERE UPPER(name) LIKE '%YABANCI HİSSE%'
   OR UPPER(name) LIKE '%YABANCI HISSE%'
""")

conn.commit()

print(
    c.execute(
        "SELECT category,COUNT(*) FROM funds GROUP BY category"
    ).fetchall()
)

conn.close()
import sqlite3

conn = sqlite3.connect("tefas.db")
c = conn.cursor()

updates = {
    "Hisse Senedi": [
        "HİSSE",
        "HISSE",
        "HİSSE SENEDİ"
    ],
    "Para Piyasası": [
        "PARA PİYASASI"
    ],
    "Altın": [
        "ALTIN"
    ],
    "Borçlanma": [
        "BORÇLANMA",
        "BORCLANMA"
    ],
    "Değişken": [
        "DEĞİŞKEN",
        "DEGISKEN"
    ],
    "Fon Sepeti": [
        "FON SEPETİ"
    ],
    "Katılım": [
        "KATILIM"
    ],
    "Yabancı": [
        "YABANCI"
    ]
}


for category, keys in updates.items():
    for key in keys:
        c.execute(
            """
            UPDATE funds
            SET category=?
            WHERE UPPER(title) LIKE ?
            """,
            (category, f"%{key}%")
        )

conn.commit()


print(
    c.execute(
        "SELECT category,COUNT(*) FROM funds GROUP BY category"
    ).fetchall()
)

conn.close()
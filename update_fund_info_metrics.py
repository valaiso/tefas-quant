import sqlite3
import datetime


DB = "tefas.db"


conn = sqlite3.connect(DB)
cursor = conn.cursor()


today = datetime.date.today().strftime("%Y-%m-%d")


# geçici veri doldurma
# gerçek TEFAS datası geldiğinde burası API ile değişecek

funds = cursor.execute(
    """
    SELECT id
    FROM funds
    WHERE status='ACTIVE'
    """
).fetchall()


for f in funds:

    fund_id = f[0]


    cursor.execute(
        """
        INSERT OR REPLACE INTO fund_info_metrics
        (
        fund_id,
        aum,
        investor_count,
        management_fee,
        withholding_tax
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            fund_id,
            0,
            0,
            2.0,   # örnek yönetim ücreti %
            0.0    # stopaj avantajı
        )
    )


conn.commit()
conn.close()


print("fund_info_metrics dolduruldu")
import sqlite3


conn = sqlite3.connect("tefas.db")
cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS fund_external_metrics (

    fund_id INTEGER PRIMARY KEY,

    risk_score REAL,

    aum REAL,
    investor_count INTEGER,

    flow_1w REAL,
    flow_1m REAL,
    flow_3m REAL,

    beta REAL,
    calmar_ratio REAL,
    real_return_1y REAL,

    portfolio_stock REAL,
    portfolio_cash REAL,
    portfolio_bond REAL,
    portfolio_gold REAL,

    category_rank INTEGER,
    category_size INTEGER,

    source TEXT DEFAULT 'fonoloji',

    updated_at TEXT,

    FOREIGN KEY(fund_id) REFERENCES funds(id)

)
""")


conn.commit()
conn.close()


print("fund_external_metrics oluşturuldu")
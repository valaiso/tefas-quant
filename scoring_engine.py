import pandas as pd
import numpy as np
import sqlite3
import datetime
import os
import json

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "tefas.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn

def ensure_column(conn, table, column, dtype):
    """Tabloda eksik bir kolon varsa güvenli bir şekilde ALTER TABLE uygular (Migration)."""
    cursor = conn.cursor()
    cols = [
        x[1] 
        for x in cursor.execute(
            f"PRAGMA table_info({table})"
        )
    ]
    if column not in cols:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {dtype}"
        )
        conn.commit()

def init_fund_scores_table(conn):
    """fund_scores tablosunu ve gelecekteki olası genişlemeler için migration destekli yapıyı hazırlar."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_scores (
            fund_id INTEGER,
            date TEXT,
            performance_score REAL,
            risk_score REAL,
            consistency_score REAL,
            stability_score REAL,
            raw_score REAL,
            confidence_score REAL,
            final_score REAL,
            category_rank INTEGER,
            category_total INTEGER,
            category_percentile REAL,
            letter_grade TEXT,
            signal TEXT,
            breakdown_json TEXT,
            PRIMARY KEY (fund_id, date)
        )
    """)
    conn.commit()

    # İleride eklenebilecek olası yeni metrik veya skor kolonları için güvenli migration kontrolü
    migration_columns = [
        ("momentum_score", "REAL"),
        ("quality_score", "REAL"),
        ("valuation_score", "REAL")
    ]
    for col_name, col_dtype in migration_columns:
        ensure_column(conn, "fund_scores", col_name, col_dtype)

def calculate_percentile_rank(series, ascending=True):
    """Verilen pandas serisini 0-100 arasında percentile skora çevirir (yüksek score = yüksek percentile)."""
    if len(series.dropna()) == 0:
        return pd.Series(50.0, index=series.index)
    if ascending:
        return series.rank(pct=True, ascending=True) * 100
    else:
        return series.rank(pct=True, ascending=False) * 100

def run_scoring_pipeline(
    conn=None,
    full_sync=False,
    history_years=5,
    fund_limit=400
):
    print(
        f"SYNC={full_sync}, YEARS={history_years}, LIMIT={fund_limit}"
    )
    print("SCORING ENGINE BAŞLADI")
    
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        init_fund_scores_table(conn)
        
        # fund_metrics ve funds tablolarını birleştirerek verileri çek
        query = """
            SELECT m.*, f.code, f.category 
            FROM fund_metrics m
            JOIN funds f ON m.fund_id = f.id
        """
        df = pd.read_sql(query, con=conn)
        print(f"Skorlanacak fon metrik sayısı: {len(df)}")
        if df.empty:
            return False, "Skorlanacak fon metrik verisi bulunamadı."

        # Fonun geçmiş uzunluğunu / veri derinliğini hesaplamak için veritabanından gün sayısını çekelim
        history_counts = pd.read_sql("""
            SELECT fund_id, COUNT(date) as day_count 
            FROM fund_daily_prices 
            GROUP BY fund_id
        """, con=conn).set_index('fund_id')['day_count']
        
        df['day_count'] = df['fund_id'].map(history_counts).fillna(0)

        # 1) BİLEŞEN SKORLARI (0-100 Normalizasyonu / Percentile Ranking)
        
        # Performance Score (%40 Ağırlık)
        perf_metrics = ['annual_return', 'sharpe_ratio', 'sortino_ratio', 'alpha', 'information_ratio', 'calmar_ratio']
        perf_rank_sum = pd.Series(0.0, index=df.index)
        for m in perf_metrics:
            if m in df.columns:
                perf_rank_sum += calculate_percentile_rank(df[m], ascending=True)
        df['performance_score'] = perf_rank_sum / len(perf_metrics)

        # Risk Score (%30 Ağırlık) - Düşük risk iyi olduğu için ascending=False
        risk_metrics = ['max_drawdown', 'volatility', 'var_95', 'cvar_95']
        risk_rank_sum = pd.Series(0.0, index=df.index)
        for m in risk_metrics:
            if m in df.columns:
                risk_rank_sum += calculate_percentile_rank(df[m], ascending=False)
        df['risk_score'] = risk_rank_sum / len(risk_metrics)

        # Consistency Score (%20 Ağırlık)
        cons_metrics = ['win_rate', 'information_ratio', 'skewness']
        cons_rank_sum = pd.Series(0.0, index=df.index)
        for m in cons_metrics:
            if m in df.columns:
                cons_rank_sum += calculate_percentile_rank(df[m], ascending=True)
        df['consistency_score'] = cons_rank_sum / len(cons_metrics)

        # Stability Score (%10 Ağırlık)
        if 'beta' in df.columns:
            df['beta_stability'] = -(df['beta'] - 1.0).abs()
        else:
            df['beta_stability'] = 0.0

        stab_metrics = ['recovery_time', 'beta_stability', 'day_count']
        stab_rank_sum = pd.Series(0.0, index=df.index)
        
        if 'recovery_time' in df.columns:
            stab_rank_sum += calculate_percentile_rank(df['recovery_time'], ascending=False)
        if 'beta_stability' in df.columns:
            stab_rank_sum += calculate_percentile_rank(df['beta_stability'], ascending=True)
        if 'day_count' in df.columns:
            stab_rank_sum += calculate_percentile_rank(df['day_count'], ascending=True)
            
        df['stability_score'] = stab_rank_sum / len(stab_metrics)

        # RAW SCORE HESAPLAMASI (Ağırlıklı Ortalama)
        df['raw_score'] = (
            df['performance_score'] * 0.40 +
            df['risk_score'] * 0.30 +
            df['consistency_score'] * 0.20 +
            df['stability_score'] * 0.10
        )

        # 2) CONFIDENCE SİSTEMİ & BASE SCORE (Yumuşatılmış: 0.85 + 0.15 * confidence)
        base_confidence = df['day_count'].apply(lambda x: min(max(x / 750.0, 0.2), 1.0))
        df['confidence_score'] = base_confidence
        df['base_score'] = df['raw_score'] * (0.85 + 0.15 * df['confidence_score'])

        # 3) KATEGORİ BAZINDA RELATİVE RANKING & PERCENTILE (100 = en iyi, 0 = en kötü)
        df['category_percentile'] = (
            df.groupby('category')['base_score']
            .rank(pct=True, ascending=True) * 100
        )
        
        df['category_rank'] = df.groupby('category')['base_score'].rank(ascending=False, method='min').astype(int)
        df['category_total'] = df.groupby('category')['base_score'].transform('count')

        # 4) FİNAL SCORE (Base Score %70 + Kategori Persentil %30) VE SCORE BOOST
        df['final_score'] = (
            df['base_score'] * 0.70 +
            df['category_percentile'] * 0.30
        )
        
        # Üstün performansları ve elit fonları gerçek rating dağılımına taşımak için Score Boost (%10 Çarpan, Max 100)
        df['final_score'] = np.minimum(
            df['final_score'] * 1.10,
            100.0
        )

        # 5) PROFESYONEL HARF NOTU VE SİNYAL ÜRETİMİ
        def assign_grade_and_signal(score):
            if score >= 95:
                return 'A+', 'GÜÇLÜ AL / ELİT'
            elif score >= 90:
                return 'A', 'AL'
            elif score >= 85:
                return 'B+', 'İYİ'
            elif score >= 75:
                return 'B', 'TUT'
            elif score >= 65:
                return 'C', 'İZLE'
            else:
                return 'D', 'ZAYIF'

        grades_signals = df['final_score'].apply(assign_grade_and_signal)
        df['letter_grade'] = [gs[0] for gs in grades_signals]
        df['signal'] = [gs[1] for gs in grades_signals]

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        score_records = []

        for _, row in df.iterrows():
            breakdown_dict = {
                "performance": round(float(row['performance_score']), 1),
                "risk": round(float(row['risk_score']), 1),
                "consistency": round(float(row['consistency_score']), 1),
                "stability": round(float(row['stability_score']), 1)
            }
            breakdown_json_str = json.dumps(breakdown_dict)

            score_records.append((
                int(row['fund_id']), today_str,
                float(row['performance_score']), float(row['risk_score']),
                float(row['consistency_score']), float(row['stability_score']),
                float(row['raw_score']), float(row['confidence_score']),
                float(row['final_score']), int(row['category_rank']),
                int(row['category_total']), float(row['category_percentile']),
                str(row['letter_grade']), str(row['signal']), str(breakdown_json_str)
            ))

        if score_records:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO fund_scores 
                (fund_id, date, performance_score, risk_score, consistency_score, stability_score, 
                 raw_score, confidence_score, final_score, category_rank, category_total, 
                 category_percentile, letter_grade, signal, breakdown_json) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, score_records)
            conn.commit()

        return True, f"Başarılı! {len(score_records)} fon için migration uyumlu, 70/30 ağırlıklı, boost destekli profesyonel skorlama tamamlandı."

    except Exception as e:
        return False, f"Scoring Engine Hatası: {str(e)}"
    finally:
        if close_conn:
            conn.close()
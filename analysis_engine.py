import pandas as pd
import numpy as np
import sqlite3
import datetime
import os
import metrics

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "tefas.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn

def init_fund_metrics_table(conn):
    """fund_metrics tablosunu ve eksik kolonları güvenli bir şekilde oluşturur / günceller."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_metrics (
            fund_id INTEGER,
            date TEXT,
            total_return REAL,
            annual_return REAL,
            volatility REAL,
            sharpe_ratio REAL,
            sortino_ratio REAL,
            calmar_ratio REAL,
            max_drawdown REAL,
            recovery_time INTEGER,
            win_rate REAL,
            var_95 REAL,
            cvar_95 REAL,
            skewness REAL,
            beta REAL,
            alpha REAL,
            information_ratio REAL,
            PRIMARY KEY (fund_id, date)
        )
    """)
    conn.commit()

def get_benchmark_returns(benchmark_returns, dates_index):
    """
    Önceden önbelleğe alınmış global benchmark getiri serisini, 
    ilgili fonun tarih indeksine göre güvenli bir şekilde hizalar.
    """
    benchmark_returns = benchmark_returns[
        ~benchmark_returns.index.duplicated()
    ]

    dates_index = pd.to_datetime(
        dates_index
    )

    bm = benchmark_returns.reindex(
        dates_index,
        method='ffill'
    )

    return bm.dropna()

def estimate_risk_free_series(daily_matrix, category_of):
    """Para piyasası fonlarının günlük medyan getirisi (zamanla değişen risksiz faiz).

    Ayarda sabit RISK_FREE_RATE verilmişse None döner.
    """
    try:
        from config.settings import RISK_FREE_RATE
    except ImportError:
        RISK_FREE_RATE = None
    if RISK_FREE_RATE is not None:
        return None
    mm_ids = [
        i for i, c in category_of.items()
        if isinstance(c, str) and c.startswith('Para Piyasas') and i in daily_matrix.columns
    ]
    mm = daily_matrix[mm_ids]
    series = mm.median(axis=1)[mm.notna().sum(axis=1) >= 5]
    return series.clip(-0.01, 0.01)


def fund_risk_free_rate(rf_series, returns_index, fallback):
    """Fonun kendi tarih aralığındaki ortalama risksiz faiz (yıllık)."""
    if rf_series is None:
        return fallback
    aligned = rf_series.reindex(returns_index).dropna()
    if len(aligned) < len(returns_index) * 0.5:
        return fallback
    return float(aligned.mean() * metrics.TRADING_DAYS)


def estimate_risk_free_rate(price_matrix, category_of):
    """Ayarda sabit oran yoksa para piyasası fonlarının son 1 yıllık medyan getirisi."""
    try:
        from config.settings import RISK_FREE_RATE, RISK_FREE_FALLBACK
    except ImportError:
        RISK_FREE_RATE, RISK_FREE_FALLBACK = None, metrics.DEFAULT_RISK_FREE_RATE
    if RISK_FREE_RATE is not None:
        return float(RISK_FREE_RATE)

    mm_ids = [
        i for i, c in category_of.items()
        if isinstance(c, str) and c.startswith('Para Piyasas') and i in price_matrix.columns
    ]
    window = price_matrix[mm_ids].iloc[-(metrics.TRADING_DAYS + 1):]
    window = window.loc[:, window.notna().sum() >= metrics.TRADING_DAYS * 0.9]
    if window.shape[1] < 5:
        return float(RISK_FREE_FALLBACK)
    yearly = window.ffill().iloc[-1] / window.bfill().iloc[0] - 1
    return float(yearly.median())


def run_analysis_pipeline(conn=None):
    print("ANALYSIS ENGINE BAŞLADI")
    
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        init_fund_metrics_table(conn)
        
        funds_df = pd.read_sql("SELECT id, code, category FROM funds WHERE status = 'ACTIVE'", con=conn)
        print(f"Fon sayısı: {len(funds_df)}")
        if funds_df.empty:
            return False, "Analiz edilecek aktif fon bulunamadı."

        prices_df = pd.read_sql("SELECT fund_id, date, price FROM fund_daily_prices ORDER BY fund_id, date ASC", con=conn)
        print(f"Fiyat kayıt sayısı: {len(prices_df)}")
        if prices_df.empty:
            return False, "Fiyat verisi bulunamadı."

        # Benchmark: her kategori için fonların günlük getirilerinin eşit ağırlıklı
        # ortalaması. (Eskiden tüm fonların FİYAT ortalaması alınıyordu; fiyat
        # seviyeleri farklı olduğu için beta/alfa anlamsız çıkıyordu.)
        print("Benchmark hazırlanıyor...")
        clean = prices_df[prices_df['price'] > 0].drop_duplicates(['fund_id', 'date'], keep='last')
        price_matrix = clean.pivot(index='date', columns='fund_id', values='price')
        price_matrix.index = pd.to_datetime(price_matrix.index)
        price_matrix = price_matrix.sort_index()
        daily_matrix = price_matrix.pct_change(fill_method=None).clip(-0.5, 1.0)
        category_of = funds_df.set_index('id')['category'].fillna('Diğer')

        category_benchmarks = {}
        for cat, ids in category_of.groupby(category_of).groups.items():
            cols = [i for i in ids if i in daily_matrix.columns]
            if cols:
                category_benchmarks[cat] = daily_matrix[cols].mean(axis=1).dropna()
        all_benchmark = daily_matrix.mean(axis=1).dropna()

        current_rf = estimate_risk_free_rate(price_matrix, category_of)
        rf_series = estimate_risk_free_series(daily_matrix, category_of)
        print(f"Benchmark hazır. Kategori: {len(category_benchmarks)} | Güncel risksiz faiz (1Y): %{current_rf*100:.1f}")

        grouped_prices = dict(tuple(prices_df.groupby('fund_id')))
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        metrics_records = []

        print(f"Analiz başladı. Toplam fon: {len(funds_df)}")
        for i, row in funds_df.iterrows():
            try:
                print(f"{i+1}/{len(funds_df)} Fon ID: {row['id']}")
                f_id = row['id']
                category = row['category']
                
                if f_id not in grouped_prices:
                    print(f"SKIP {row['code']} : grouped_prices içinde yok")
                    continue
                    
                f_history = grouped_prices[f_id].copy()
                f_history['date_dt'] = pd.to_datetime(
                    f_history['date']
                )
                f_history = (
                    f_history[
                        f_history['price'] > 0
                    ]
                    .groupby('date_dt')
                    .last()
                    .sort_index()
                )
                prices = f_history['price'].values
                if row['code'] in ['BAI','BGR','EDN','HDD','HFO','IH1','KCR','PA2','PK1','RFM','SD1','SHC','YSH','ZPO']:
                    print(f"CHECK {row['code']} ham={len(grouped_prices[f_id])} temiz={len(prices)}")
                
                if len(prices) < 14:
                    print(f"SKIP {row['code']} : sadece {len(prices)} günlük veri var.")
                    continue

                prices_series = f_history['price']
                returns = prices_series.pct_change().dropna()
                print(f"DEBUG {row['code']} fiyat={len(prices)} getiri={len(returns)}")

                try:
                    # --- METRİK HESAPLAMALARI (metrics.py çağrıları) ---
                    tot_return = metrics.calculate_total_return(prices)
                    ann_return = metrics.calculate_annual_return(prices)
                    volatility = metrics.calculate_volatility(returns)
                    
                    mdd, recovery_time = metrics.calculate_drawdown_metrics(prices)
                    
                    # Fonun kendi dönemindeki ortalama faiz: 2021-23'ün düşük ve
                    # 2024-26'nın yüksek faizini aynı sabit oranla ölçmemek için.
                    risk_free_rate = fund_risk_free_rate(rf_series, returns.index, current_rf)
                    sharpe = metrics.calculate_sharpe_ratio(returns, risk_free_rate)
                    sortino = metrics.calculate_sortino_ratio(returns, risk_free_rate)
                    calmar = metrics.calculate_calmar_ratio(ann_return, mdd)
                    
                    win_rate = metrics.calculate_win_rate(returns)
                    var_95, cvar_95 = metrics.calculate_var_cvar(returns, confidence_level=0.95)
                    skewness = metrics.calculate_skewness(returns)
                    
                    # Benchmark & Alpha / Beta / Information Ratio
                    benchmark_returns = category_benchmarks.get(
                        category if pd.notna(category) else 'Diğer', all_benchmark
                    )
                    bm_returns = get_benchmark_returns(benchmark_returns, returns.index)
                    beta, alpha = metrics.calculate_beta_and_alpha(
                        returns, bm_returns, risk_free_rate
                    )
                    info_ratio = metrics.calculate_information_ratio(returns, bm_returns)
                    print(f"DEBUG {row['code']} beta={beta} alpha={alpha} info={info_ratio}")

                    print(f"OK {row['code']}")
                    metrics_records.append((
                        int(f_id), today_str,
                        float(tot_return), float(ann_return), float(volatility),
                        float(sharpe), float(sortino), float(calmar),
                        float(mdd), int(recovery_time), float(win_rate),
                        float(var_95), float(cvar_95), float(skewness),
                        float(beta), float(alpha), float(info_ratio)
                    ))
                except Exception as e:
                    print("="*50)
                    print("HATA FON:", row['code'])
                    print("ID:", f_id)
                    print("HATA:", repr(e))
                    import traceback
                    traceback.print_exc()
                    print("="*50)
                    continue

            except Exception as e:
                print(f"HATA: {row['code']} -> {e}")

        if metrics_records:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO fund_metrics 
                (fund_id, date, total_return, annual_return, volatility, sharpe_ratio, sortino_ratio, 
                 calmar_ratio, max_drawdown, recovery_time, win_rate, var_95, cvar_95, skewness, 
                 beta, alpha, information_ratio) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, metrics_records)
            conn.commit()

        return True, f"Başarılı! {len(metrics_records)} fon için finansal metrikler hesaplandı ve kaydedildi."

    except Exception as e:
        return False, f"Analysis Engine Hatası: {str(e)}"
    finally:
        if close_conn:
            conn.close()

if __name__ == "__main__":
    success, msg = run_analysis_pipeline()
    print(msg)
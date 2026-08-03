import pandas as pd
import numpy as np
from datetime import datetime
from database.database import SessionLocal
from database.models import Fund, FundDailyPrice

def run_analysis_engine():
    print("📊 3. Aşama: Analiz Motoru Çalıştırılıyor (Sharpe, Alpha, Beta, Z-Score)...")
    db = SessionLocal()
    funds = db.query(Fund).all()
    
    if not funds:
        print("⚠️ Veritabanında fon bulunamadı.")
        db.close()
        return
        
    # Tüm fonların fiyat geçmişini bir DataFrame'de topluyoruz (Market proxy için)
    data = {}
    for fund in funds:
        prices = db.query(FundDailyPrice).filter(FundDailyPrice.fund_id == fund.id).order_by(FundDailyPrice.date.asc()).all()
        if len(prices) >= 10:
            data[fund.code] = {p.date: p.price for p in prices}
            
    df_prices = pd.DataFrame(data).dropna()
    if df_prices.empty:
        print("⚠️ Yeterli örtüşen fiyat verisi bulunamadı.")
        db.close()
        return
        
    # Günlük getiriler
    df_returns = df_prices.pct_change().dropna()
    
    # Piyasa Getirisi (Takip edilen fonların ortalaması - Market Proxy)
    market_returns = df_returns.mean(axis=1)
    
    # Riskten arındırılmış oran varsayımı (Yıllık %40, günlük karşılığı)
    risk_free_rate_daily = 0.40 / 252
    
    print("-" * 90)
    print(f"{'FON':<6} | {'GETİRİ':<8} | {'SHARPE':<8} | {'BETA':<6} | {'ALPHA':<8} | {'Z-SCORE':<8}")
    print("-" * 90)
    
    results = []
    for code in df_returns.columns:
        fund_ret = df_returns[code]
        total_ret = (df_prices[code].iloc[-1] - df_prices[code].iloc[0]) / df_prices[code].iloc[0]
        
        # Sharpe Oranı (Yıllıklandırılmış)
        mean_daily_ret = fund_ret.mean()
        std_daily_ret = fund_ret.std()
        sharpe = (mean_daily_ret - risk_free_rate_daily) / std_daily_ret * np.sqrt(252) if std_daily_ret > 0 else 0
        
        # Beta ve Alpha Hesaplama
        covariance = np.cov(fund_ret, market_returns)[0][1]
        market_variance = np.var(market_returns)
        beta = covariance / market_variance if market_variance > 0 else 1.0
        
        expected_return = risk_free_rate_daily + beta * (market_returns.mean() - risk_free_rate_daily)
        alpha = (mean_daily_ret - expected_return) * 252 # Yıllıklandırılmış Alpha
        
        results.append({
            "code": code,
            "total_ret": total_ret,
            "sharpe": sharpe,
            "beta": beta,
            "alpha": alpha,
            "mean_ret": mean_daily_ret
        })
        
    # Z-Score Hesaplama (Getirilere göre istatistiksel sapma)
    rets = [r["total_ret"] for r in results]
    mean_ret_all = np.mean(rets)
    std_ret_all = np.std(rets) if np.std(rets) > 0 else 1.0
    
    for r in results:
        z_score = (r["total_ret"] - mean_ret_all) / std_ret_all
        r["z_score"] = z_score
        print(f"{r['code']:<6} | %{r['total_ret']*100:<7.2f} | {r['sharpe']:<8.2f} | {r['beta']:<6.2f} | %{r['alpha']*100:<7.2f} | {r['z_score']:<8.2f}")
        
    print("-" * 90)
    db.close()
    print("🎉 Analiz Motoru başarıyla tamamlandı ve metrikler hesaplandı!")

if __name__ == "__main__":
    run_analysis_engine()
import pandas as pd
import numpy as np

def calculate_fund_scores(df):
    """
    df: Fon verilerini içeren DataFrame (Kolonlar: Kategori, Sharpe, MaxDrawdown, Momentum_180d, YonetimUcreti vb.)
    """
    scored_dfs = []
    
    # Her fonu kendi kategorisi içinde (peers) değerlendiriyoruz
    for category, group in df.groupby('Kategori'):
        
        # 1. Kategori içi yüzde dilim (percentile) sıralamaları (0 ile 1 arasında)
        group['Sharpe_Pct'] = group['Sharpe'].rank(pct=True, ascending=True)
        group['Momentum_Pct'] = group['Momentum_180d'].rank(pct=True, ascending=True)
        
        # Max Drawdown için düşük düşüş daha iyidir, ters sıralanır
        group['Drawdown_Pct'] = group['MaxDrawdown'].rank(pct=True, ascending=False)
        
        # Yönetim ücreti düşük olan avantajlıdır, ters sıralanır
        group['Fee_Pct'] = group['YonetimUcreti'].rank(pct=True, ascending=False)
        
        # 2. Ağırlıklı Skor Formülü (Sharpe %40, Momentum %30, Drawdown %20, Ücret %10)
        group['Final_Score'] = (
            (group['Sharpe_Pct'] * 0.40) +
            (group['Momentum_Pct'] * 0.30) +
            (group['Drawdown_Pct'] * 0.20) +
            (group['Fee_Pct'] * 0.10)
        ) * 100  # 0 - 100 skalasına çekiyoruz
        
        scored_dfs.append(group)
        
    return pd.concat(scored_dfs)
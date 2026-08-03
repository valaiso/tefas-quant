import pandas as pd
from app.services.ranking import calculate_category_percentiles
from app.services.scoring_engine import QuantitativeFundScorer

# Örnek Test Verisi
data = [
    {
        "fund_code": "XYZ", "category": "Hisse", 
        "return_1y": 120.0, "return_3m": 15.0, "alpha": 10.0, "information_ratio": 1.5,
        "sharpe_ratio": 2.1, "sortino_ratio": 3.0, "volatility": 12.0, "max_drawdown": -8.0,
        "investor_growth_1m": 5.0, "aum_growth_1m": 8.0, "fund_age_years": 5.0, "management_fee": 2.0
    },
    {
        "fund_code": "ABC", "category": "Hisse", 
        "return_1y": 50.0, "return_3m": -5.0, "alpha": 2.0, "information_ratio": 0.5,
        "sharpe_ratio": 0.8, "sortino_ratio": 1.0, "volatility": 25.0, "max_drawdown": -22.0,
        "investor_growth_1m": 20.0, "aum_growth_1m": 2.0, "fund_age_years": 2.0, "management_fee": 3.5
    }
]

df = pd.DataFrame(data)

# 1. Kategori içi sıralamayı hesapla
ranked_df = calculate_category_percentiles(df)

# 2. Skorları hesapla ve ekrana yazdır
for _, row in ranked_df.iterrows():
    scorer = QuantitativeFundScorer(row)
    result = scorer.calculate_scores()
    print("\n------------------------------")
    print(f"Fon Kodu     : {result['fund_code']}")
    print(f"Toplam Skor  : {result['total_score']} / 100")
    print(f"Kalite Grubu : {result['grade']}")
    print(f"Sinyal       : {result['signal']}")
    print(f"Uygulanan Cezalar: {result['applied_penalties']}")
    print("------------------------------")
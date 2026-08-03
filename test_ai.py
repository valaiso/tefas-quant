import json
from ai_engine import generate_fund_analysis

# Senin belirlediğin örnek veri sözleşmesi (Contract)
sample_metrics = {
  "fund": "AFT",
  "score": 92,
  "signal": "BUY",
  "category": "Hisse Senedi Yoğun",
  "category_rank": 2,
  "category_size": 84,
  "momentum": 91,
  "volatility": 18.2,
  "sharpe": 2.14,
  "sortino": 3.02,
  "alpha": 4.18,
  "beta": 0.86,
  "information_ratio": 1.74,
  "max_drawdown": 8.4,
  "market_regime": "Risk-Off",
  "anomaly": False,
  "confidence": 97
}

print("-> Yapay Zeka Yorum Motoru test ediliyor...")
# Not: OpenAI API Key ayarlı olmalıdır (örn: set OPENAI_API_KEY=sk-...)
result = generate_fund_analysis(sample_metrics)
print("\n--- ÜRETİLEN AI JSON RAPORU ---")
print(json.dumps(result, ensure_ascii=False, indent=4))
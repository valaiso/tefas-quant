import pandas as pd

from app.services.scoring_engine import (
    calculate_performance_composite,
    calculate_risk_composite,
    calculate_quality_composite,
    calculate_cashflow_composite,
    calculate_cost_composite,
    calculate_absolute_score,
    calculate_final_score,
    calculate_rating
)


data = [
    {
        "category": "Hisse",
        "r_365": 120,
        "r_180": 50,
        "r_90": 20,
        "r_30": 10,
        "sharpe": 2.1,
        "sortino": 3.0,
        "volatility": 0.12,
        "mdd": 8,
        "age_years": 5,
        "depth_score": 90
    },
    {
        "category": "Hisse",
        "r_365": 50,
        "r_180": 20,
        "r_90": 5,
        "r_30": -5,
        "sharpe": 0.8,
        "sortino": 1.0,
        "volatility": 0.25,
        "mdd": 22,
        "age_years": 2,
        "depth_score": 50
    }
]


df = pd.DataFrame(data)


perf = calculate_performance_composite(df)
risk = calculate_risk_composite(df)
quality = calculate_quality_composite(df)
cash = calculate_cashflow_composite(df)
cost = calculate_cost_composite(df)


absolute = calculate_absolute_score(
    perf,
    risk,
    quality,
    cash,
    cost
)


for i in range(len(df)):

    final_score, raw_score, confidence_factor = calculate_final_score(
        absolute.iloc[i],
        0,
        80
    )

    grade, signal = calculate_rating(
        final_score,
        80
    )

    print("------------------------------")
    print("Fon:", i + 1)
    print("Absolute Score:", absolute.iloc[i])
    print("Final Score:", final_score)
    print("Grade:", grade)
    print("Signal:", signal)
    print("------------------------------")
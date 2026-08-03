import pandas as pd

def calculate_category_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    ranked_dfs = []
    for category_name, group in df.groupby('category'):
        g = group.copy()
        g['rank_return_1y'] = g['return_1y'].rank(pct=True) * 100
        g['rank_alpha'] = g['alpha'].rank(pct=True) * 100
        g['rank_info_ratio'] = g['information_ratio'].rank(pct=True) * 100
        g['rank_sharpe'] = g['sharpe_ratio'].rank(pct=True) * 100
        g['rank_sortino'] = g['sortino_ratio'].rank(pct=True) * 100
        g['rank_investor_growth'] = g['investor_growth_1m'].rank(pct=True) * 100
        g['rank_aum_growth'] = g['aum_growth_1m'].rank(pct=True) * 100
        g['rank_fund_age'] = g['fund_age_years'].rank(pct=True) * 100
        g['rank_volatility'] = g['volatility'].rank(pct=True, ascending=False) * 100
        g['rank_max_drawdown'] = g['max_drawdown'].rank(pct=True, ascending=False) * 100
        g['rank_management_fee'] = g['management_fee'].rank(pct=True, ascending=False) * 100
        ranked_dfs.append(g)
    return pd.concat(ranked_dfs, ignore_index=True)
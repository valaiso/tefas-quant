class LongTermScanner:
    def __init__(self, db_session):
        self.db = db_session

    def calculate_long_term_score(self, fund_data):
        score = (
            (fund_data.get('cagr_5y', 0) * 0.35) +
            (fund_data.get('sharpe', 0) * 0.25) +
            (fund_data.get('max_drawdown_quality', 0) * 0.20) +
            (fund_data.get('annual_stability', 0) * 0.15) +
            (fund_data.get('confidence', 0) * 0.05)
        )
        return round(score, 2)

    def get_champions(self, limit=10):
        raw_funds = []
        scored_funds = []
        for fund in raw_funds:
            fund['long_term_score'] = self.calculate_long_term_score(fund)
            scored_funds.append(fund)

        scored_funds.sort(key=lambda x: x['long_term_score'], reverse=True)
        return scored_funds[:limit]
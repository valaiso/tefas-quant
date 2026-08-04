class QuantStarScanner:
    def __init__(self, db_session):
        self.db = db_session

    def calculate_score(self, fund_data):
        score = (
            (fund_data.get('performance', 0) * 0.35) +
            (fund_data.get('sharpe', 0) * 0.25) +
            (fund_data.get('momentum', 0) * 0.15) +
            (fund_data.get('drawdown_score', 0) * 0.15) +
            (fund_data.get('confidence_score', 0) * 0.10)
        )
        return round(score, 2)

    def get_top_funds(self, limit=10):
        raw_funds = []
        scored_funds = []
        for fund in raw_funds:
            fund['quant_star_score'] = self.calculate_score(fund)
            scored_funds.append(fund)
            
        scored_funds.sort(key=lambda x: x['quant_star_score'], reverse=True)
        return scored_funds[:limit]
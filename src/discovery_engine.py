from src.quant_star import QuantStarScanner
from src.momentum_scanner import MomentumScanner
from src.long_term_scanner import LongTermScanner

class DiscoveryEngine:
    def __init__(self, db_session):
        self.db = db_session
        self.quant_star_scanner = QuantStarScanner(self.db)
        self.momentum_scanner = MomentumScanner(self.db)
        self.long_term_scanner = LongTermScanner(self.db)

    def run_all_scans(self):
        return {
            "quant_stars": self.quant_star_scanner.get_top_funds(limit=10),
            "momentum_leaders": self.momentum_scanner.scan_momentum(),
            "long_term_champions": self.long_term_scanner.get_champions(limit=10)
        }
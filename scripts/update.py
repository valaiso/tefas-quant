#!/usr/bin/env python3
"""Günlük veri hattı: TEFAS'tan çek -> 3 yıla buda -> skorla -> statik siteyi üret.

Kullanım
--------
    python scripts/update.py               # artımlı güncelleme + site
    python scripts/update.py --full        # 3 yılı baştan çek
    python scripts/update.py --skip-fetch  # yalnızca skor ve site
    python scripts/update.py --budget-min 20  # geçmiş doldurmayı 20 dk ile sınırla
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant import backtest, benchmarks, export, fetch, scoring, simulation  # noqa: E402
from quant.db import DEFAULT_DB, ROOT, open_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--delay", type=float, default=3.0, help="TEFAS istekleri arası saniye")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--budget-min", type=float, default=None,
                        help="Geçmiş doldurma için azami dakika (CI'da ilk kurulumu böler)")
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    started = time.time()
    conn = open_db(args.db)
    if not args.skip_fetch:
        fetch.update(conn, delay=args.delay, full=args.full, budget_min=args.budget_min)
    result = scoring.run(conn)
    meta = export.build(result, Path(args.out))
    funds = scoring.load_funds(conn)
    bt = backtest.run(result["panel"], funds)
    baskets = bt.pop("_baskets")
    export.write_backtest(bt, Path(args.out))
    print(f"[backtest] {len(bt['signalDates'])} ay, {bt['observations']} A+ gözlemi", flush=True)

    print("[kıyas] dolar, altın, TÜFE, PPF", flush=True)
    bench = benchmarks.collect(result["panel"]["price"], funds["category"])
    export.write_benchmarks(bench, Path(args.out))
    sim = simulation.run(result["panel"]["price"], baskets, bench, funds["category"])
    export.write_json(Path(args.out) / "data" / "simulation.json", sim)
    if sim.get("available"):
        st = sim["stats"]["aplus_public"]
        print(f"[simülasyon] {sim['dates'][0]} – {sim['dates'][-1]}: A+ sepeti %{st['total']}, "
              f"PPF %{sim['stats']['ppf']['total']}", flush=True)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(
        f"Bitti: {meta['fundCount']} fon, son fiyat {meta['lastDataDate']},"
        f" {len(meta['excluded'])} dışlandı ({time.time() - started:.0f} sn).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

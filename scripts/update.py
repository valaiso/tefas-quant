#!/usr/bin/env python3
"""Günlük veri hattı: TEFAS'tan çek -> 3 yıla buda -> skorla -> statik siteyi üret.

Kullanım
--------
    python scripts/update.py               # artımlı güncelleme + site
    python scripts/update.py --full        # 3 yılı baştan çek
    python scripts/update.py --skip-fetch  # yalnızca skor ve site
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant import export, fetch, scoring  # noqa: E402
from quant.db import DEFAULT_DB, ROOT, open_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--delay", type=float, default=3.0, help="TEFAS istekleri arası saniye")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    started = time.time()
    conn = open_db(args.db)
    if not args.skip_fetch:
        fetch.update(conn, delay=args.delay, full=args.full)
    result = scoring.run(conn)
    meta = export.build(result, Path(args.out))
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

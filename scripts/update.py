#!/usr/bin/env python3
"""Günlük veri hattı: TEFAS'tan çek -> 5 yıla buda -> skorla -> statik siteyi üret.

Kullanım
--------
    python scripts/update.py               # artımlı güncelleme + site
    python scripts/update.py --full        # tüm pencereyi baştan çek
    python scripts/update.py --skip-fetch  # yalnızca skor ve site
    python scripts/update.py --budget-min 20  # geçmiş doldurmayı 20 dk ile sınırla
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant import backtest, benchmarks, bes, export, fetch, kap, model, report, robust, scoring, simulation  # noqa: E402
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
    parser.add_argument("--kap-budget-min", type=float, default=12.0,
                        help="KAP Portföy Dağılım Raporu taraması için azami dakika (0: atla)")
    args = parser.parse_args()

    started = time.time()
    conn = open_db(args.db)
    if not args.skip_fetch:
        fetch.update(conn, delay=args.delay, full=args.full, budget_min=args.budget_min)
        if args.kap_budget_min > 0:
            try:
                # Yalnızca halka açık fonlar (nitelikli / serbest zaten en fazla B); önce son notu A+ / A olanlar
                prio = [r[0] for r in conn.execute(
                    "SELECT f.code FROM funds f LEFT JOIN (SELECT code, signal FROM scores WHERE date = (SELECT MAX(date) FROM scores)) s"
                    " ON s.code = f.code ORDER BY CASE s.signal WHEN 'GÜÇLÜ AL' THEN 0 WHEN 'AL' THEN 1 WHEN 'İZLE' THEN 2 ELSE 3 END")]
                public = set(scoring.load_funds(conn).query("qualified == 0").index)
                kap.update(conn, codes=[c for c in prio if c in public], budget_min=args.kap_budget_min)
            except Exception as e:  # noqa: BLE001 - KAP erişilemezse eski raporlarla devam
                print(f"[kap] tarama atlandı: {e}", flush=True)
    result = scoring.run(conn)
    meta = export.build(result, Path(args.out))
    funds = scoring.load_funds(conn)
    bt = backtest.run(result["panel"], funds)
    baskets = bt.pop("_baskets")
    export.write_backtest(bt, Path(args.out))
    print(f"[backtest] {len(bt['signalDates'])} ay, {bt['observations']} A+ gözlemi", flush=True)

    print("[kıyas] dolar, altın, S&P 500, TÜFE, PPF", flush=True)
    bench = benchmarks.collect(result["panel"]["price"], funds["category"])
    export.write_benchmarks(bench, Path(args.out))
    sim = simulation.run(result["panel"]["price"], baskets, bench, funds["category"])
    export.write_json(Path(args.out) / "data" / "simulation.json", sim)
    if sim.get("available"):
        st = sim["stats"]["aplus_public"]
        print(f"[simülasyon] {sim['dates'][0]} – {sim['dates'][-1]}: A+ sepeti %{st['total']}, "
              f"PPF %{sim['stats']['ppf']['total']}", flush=True)
    mdl = model.run(result["panel"], funds, result["scored"], bench, baskets)
    try:  # ayar duyarlılığı ve ileriye doğru test (başarısız olursa model yine yayımlanır)
        robust.attach(mdl, result["panel"], funds, result["scored"], bench, baskets)
        for p in mdl["profiles"].values():
            r = p.get("robust") or {}
            wf = r.get("walkForward") or {}
            print(f"[sağlamlık] {p['label']}: {r.get('n')} ayar %{r.get('min')} – %{r.get('max')} (ortanca %{r.get('median')}) · "
                  f"ileriye doğru %{wf.get('total')} (bugünkü ayar %{wf.get('base')})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[sağlamlık] hesaplanamadı: {e}", flush=True)
    export.write_json(Path(args.out) / "data" / "model.json", mdl)
    for key, p in mdl["profiles"].items():
        st = p["backtest"].get("stats", {}).get("model", {})
        print(f"[model] {p['label']} ({p['formed']}): "
              + ", ".join(f"{b['c']} %{b['w']}" for b in p["basket"])
              + f" · geçmiş %{st.get('total')}", flush=True)
    # BES: ayrı skorlama ve uzun vadeli şirket modelleri; hatası siteyi durdurmaz
    bm = None
    try:
        bres = bes.run(conn)
        if bres is not None:
            export.write_bes(bres, Path(args.out))
            bm = bes.model_run(bres, bench)
            export.write_json(Path(args.out) / "data" / "bes_model.json", bm)
            bb = (bm.get("befas") or {}).get("basket", [])
            print(f"[bes model] BEFAS sepeti: " + ", ".join(f"{x['c']} %{x['w']}" for x in bb)
                  + f" · sonraki yenileme {bm['nextRebalance']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"[bes] üretilemedi: {exc}", flush=True)
    rp = report.build(mdl, bm, bench)
    export.write_json(Path(args.out) / "data" / "model_report.json", rp)
    print(f"[model rapor] {', '.join(m['label'] + ' ' + str(len(m['dates'])) + ' nokta' for m in rp['models'])}", flush=True)
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

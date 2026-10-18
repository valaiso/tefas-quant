"""Tüm veri hattını sırayla çalıştırır: fiyatlar -> FVT -> metrikler -> skorlar.

Kullanım: python run_pipeline.py [--skip-fetch]
"""
import argparse
import subprocess
import sys

STEPS = [
    ("TEFAS fiyatları", ["fetch_recent_prices.py"]),
    ("FVT fon bilgileri", ["sync_fvt_metrics.py"]),
    ("Risk/performans metrikleri", ["analysis_engine.py"]),
    ("Skorlama", ["scoring.py"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true", help="Sadece metrik ve skor")
    args = parser.parse_args()

    steps = STEPS[2:] if args.skip_fetch else STEPS
    for name, script in steps:
        print(f"\n=== {name} ===", flush=True)
        result = subprocess.run([sys.executable, *script])
        if result.returncode != 0:
            print(f"!!! {name} başarısız (çıkış kodu {result.returncode}), durduruldu.")
            sys.exit(result.returncode)
    print("\nVeri hattı tamamlandı.")


if __name__ == "__main__":
    main()

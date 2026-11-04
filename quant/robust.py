"""Model kurallarının sağlamlığı: ayar duyarlılığı ve ileriye doğru test.

Model, elle seçilmiş sayılarla çalışır (korelasyon sınırı, en düşük puan, oynaklık sınırı…). Bu sayılar aynı
geçmiş veriye bakılarak seçildiği için tek bir geçmiş test sonucu iyimser olabilir (aşırı uyum; Bailey ve
López de Prado). Burada iki şey ölçülür ve sitede gösterilir:

1. Ayar duyarlılığı: her ayar komşu değerleriyle (bir aşağı, bir yukarı) tek tek denenir. Sonuçların aralığı
   geçmiş testin ne kadar şansa bağlı olduğunu gösterir; sitede tek sayı yerine bu aralık verilir.
2. İleriye doğru test: her ay yalnızca o güne kadarki son 12 ayda en iyi sonucu veren ayar seçilir ve bir
   sonraki ay o ayarla yatırım yapılmış sayılır. "Ayarı geçmişe bakarak seçmenin" dürüst sonucudur.

Getiriler vergi ve valör sonrasıdır (model.run içindeki gerçekçi test).
"""
from __future__ import annotations

import copy
from contextlib import contextmanager

import numpy as np

from . import model

# Bugünkü ayarların komşuları (tek tek denenir). Profil risk sınırları profilin tanımıdır, getiriye göre seçilmez;
# yalnızca duyarlılığı gösterilir.
NEIGHBORS = [
    ("Korelasyon sınırı", {"corr_shift": -0.05}, "-0,05"), ("Korelasyon sınırı", {"corr_shift": 0.05}, "+0,05"),
    ("En düşük puan", {"profiles": {"*": {"min_score": 30}}}, "30"), ("En düşük puan", {"profiles": {"*": {"min_score": 50}}}, "50"),
    ("Süreklilik puanı", {"STAY_BONUS": 5.0}, "5"), ("Süreklilik puanı", {"STAY_BONUS": 15.0}, "15"),
    ("Sıçrama sınırı", {"SPIKE_SHARE": 0.35}, "%35"), ("Sıçrama sınırı", {"SPIKE_SHARE": 0.45}, "%45"),
    ("Risk sınırı", {"profiles": {"guvenli": {"vol": (0.0, 0.05), "mdd": -0.04}, "dengeli": {"vol": (0.04, 0.175), "mdd": -0.175},
                                  "atak": {"vol": (0.08, 0.30), "mdd": -0.30}}}, "dar"),
    ("Risk sınırı", {"profiles": {"guvenli": {"vol": (0.0, 0.07), "mdd": -0.06}, "dengeli": {"vol": (0.04, 0.225), "mdd": -0.225},
                                  "atak": {"vol": (0.08, 0.40), "mdd": -0.40}}}, "geniş"),
]
LOOKBACK = 12  # ileriye doğru testte ayar seçimi için geriye bakılan ay


@contextmanager
def override(cfg: dict):
    """Model ayarlarını geçici olarak değiştirir; çıkışta eski hâline döner."""
    special = ("profiles", "corr_shift")
    saved = {k: getattr(model, k) for k in cfg if k not in special}
    saved_profiles = copy.deepcopy(model.PROFILES)
    try:
        for k, v in cfg.items():
            if k not in special:
                setattr(model, k, v)
        if cfg.get("corr_shift"):  # her profilin kendi korelasyon sınırı kaydırılır (Güvenli'de sınır yok)
            for prof in model.PROFILES.values():
                base = prof.get("max_corr", model.MAX_CORR) if "max_corr" in prof else model.MAX_CORR
                if base is not None:
                    prof["max_corr"] = round(base + cfg["corr_shift"], 4)
        for pk, ch in (cfg.get("profiles") or {}).items():
            for key in (model.PROFILES if pk == "*" else [pk]):
                model.PROFILES[key].update(ch)
        yield
    finally:
        for k, v in saved.items():
            setattr(model, k, v)
        model.PROFILES.clear()
        model.PROFILES.update(saved_profiles)


def _monthly(bt: dict):
    v = np.asarray(bt["series"].get("modelNet") or bt["series"]["model"], dtype=float)
    return v[1:] / v[:-1] - 1


def run_configs(panel, funds, scored, bench, baskets, configs: list[tuple[str, dict, str]]) -> list[dict]:
    out = []
    for group, cfg, label in configs:
        with override(cfg):
            o = model.run(panel, funds, scored, bench, baskets)
        out.append({"group": group, "label": label, "profiles": {
            k: {"net": p["backtest"]["stats"].get("modelNet", {}).get("total"), "gross": p["backtest"]["stats"]["model"]["total"],
                "monthly": _monthly(p["backtest"]), "dates": p["backtest"]["dates"]}
            for k, p in o["profiles"].items() if p["backtest"].get("available")}})
    return out


def walk_forward(runs: list[dict], key: str, lookback: int = LOOKBACK) -> dict | None:
    """Her ay son `lookback` ayda en iyi ayarı seçip sonraki ayı onunla geçirir."""
    series = [r["profiles"][key]["monthly"] for r in runs if key in r["profiles"]]
    if not series or len({len(s) for s in series}) != 1 or len(series[0]) <= lookback + 1:
        return None
    M = np.vstack(series)  # ayar × ay
    picks, rets = [], []
    for t in range(lookback, M.shape[1]):
        trail = np.prod(1 + M[:, t - lookback:t], axis=1)
        j = int(np.argmax(trail))
        picks.append(j)
        rets.append(M[j, t])
    base = M[0, lookback:]
    dates = runs[0]["profiles"][key]["dates"]
    return {"from": dates[lookback], "to": dates[-1], "months": len(rets),
            "total": round((float(np.prod(1 + np.asarray(rets))) - 1) * 100, 2),
            "base": round((float(np.prod(1 + base)) - 1) * 100, 2),
            "switches": int(sum(a != b for a, b in zip(picks, picks[1:])))}


def attach(mdl: dict, panel, funds, scored, bench, baskets) -> dict:
    """Bugünkü ayar ve komşularıyla duyarlılık ve ileriye doğru testi hesaplar, model.json profillerine ekler."""
    runs = run_configs(panel, funds, scored, bench, baskets, [("Bugünkü ayar", {}, "bugün"), *NEIGHBORS])
    for key, p in mdl["profiles"].items():
        rows = [(r["group"], r["label"], r["profiles"][key]["net"], r["profiles"][key]["gross"]) for r in runs if key in r["profiles"]]
        nets = [x[2] for x in rows if x[2] is not None]
        if not nets:
            continue
        p["robust"] = {
            "n": len(nets), "min": round(min(nets), 1), "median": round(float(np.median(nets)), 1), "max": round(max(nets), 1),
            "base": rows[0][2],
            "rows": [{"group": g, "label": lab, "net": n, "gross": gr} for g, lab, n, gr in rows],
            "walkForward": walk_forward(runs, key),
        }
    return mdl

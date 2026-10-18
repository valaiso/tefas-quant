"""TEFAS Quant ayarları."""

# Yıllık risksiz faiz (ondalık). None: para piyasası fonlarının son 252 işlem
# günündeki medyan getirisi kullanılır (TLREF'e yakın, veriden türetilir).
RISK_FREE_RATE = None
RISK_FREE_FALLBACK = 0.40

# Son fiyatı evrenin son fiyat gününden bu kadar takvim günü eski olan fonlar
# (askıya alınmış / tasfiyedeki / kapanmış) skorlanmaz.
STALE_PRICE_DAYS = 7

# Kategori içi 1 yıllık getiri anomalisi: robust z = (r - medyan) / IQR.
# Eşiği aşan her birim için ANOMALY_PENALTY_PER_Z puan, en fazla ANOMALY_MAX_PENALTY.
# Pürüzsüz ama kategorisinin çok üstünde getiri yazan fonlar (ör. Eylül 2026
# Tera Portföy fonları) risk metriklerinde "kusursuz" göründüğü için eklendi.
ANOMALY_Z_THRESHOLD = 3.0
ANOMALY_PENALTY_PER_Z = 2.0
ANOMALY_MAX_PENALTY = 15.0

# "relative": notlar kategori içi dağılımla verilir (Morningstar benzeri
# %10 / %22.5 / %35 / %22.5 / %10). "absolute": eski sabit eşikler (85/75/65/55).
RATING_MODE = "relative"

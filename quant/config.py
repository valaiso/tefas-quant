"""TEFAS Quant ayarları: veri saklama, puanlama ağırlıkları ve cezalar."""

# ------------------------------------------------------------------ veri
# Saklanan geçmiş (yıl). Tüm metrikler ve skorlar bu pencereden hesaplanır.
HISTORY_YEARS = 3
# Budama sırasında pencerenin başına eklenen tampon (3Y getirisi için 756.
# işlem gününden önceki fiyat da gerekir).
RETENTION_BUFFER_DAYS = 20
# Artımlı güncellemede geriye dönük tekrar çekilen gün (TEFAS geç düzeltmeleri).
OVERLAP_DAYS = 7
# Resmî kategori eşlemesi ve FVT ücret/stopaj bilgisi bu kadar günde bir yenilenir.
CATEGORY_REFRESH_DAYS = 7
FVT_REFRESH_DAYS = 7

# ------------------------------------------------------------- evren
# Skorlanacak fon için gereken en az işlem günü.
MIN_HISTORY_DAYS = 60
# Son fiyatı evrenin son gününden bu kadar takvim günü eski olan fonlar
# (askıya alınmış / tasfiyedeki / kapanmış) skorlanmaz.
STALE_PRICE_DAYS = 7
# Göreli notlama ve anomali için kategoride gereken en az fon.
MIN_CATEGORY_SIZE = 5

# ------------------------------------------------------------- skor (model v2)
# v2, 3 yıllık TEFAS verisinde point-in-time test edildi (2024-10 – 2026-07,
# 22 ay, kategori içi rank IC, 3 aylık ileri getiri, T+2 giriş): v1 0,243 ->
# v2 0,273. Bütün alt metrikler kategori içi yüzdeliğe çevrilir.
MODEL_VERSION = "v2"

# Nihai kalite skoru ağırlıkları (toplam 1.0)
COMPONENT_WEIGHTS = {
    "performance": 0.40,
    "risk": 0.30,
    "cost": 0.15,
    "investor": 0.10,
    "portfolio": 0.05,
}

# Performans: işlem günü penceresi -> ağırlık. Testte 6A ve 1Y getiri en güçlü
# öngörücüydü; 2A ve 3Y ek bilgi katmadı (3Y yalnızca gösterilir).
PERFORMANCE_WINDOWS = {
    "1a": (21, 0.10),
    "3a": (63, 0.20),
    "6a": (126, 0.35),
    "1y": (252, 0.35),
}
# Ekranda gösterilen getiri dönemleri (skora girmeyenler dahil)
DISPLAY_WINDOWS = {"1a": 21, "2a": 42, "3a": 63, "6a": 126, "1y": 252, "3y": 756}

# Risk (son 252 işlem günü): metrik -> (ağırlık, yüksek değer iyi mi)
RISK_METRICS = {
    "sharpe": (0.40, True),
    "mdd": (0.30, False),      # maksimum düşüş: düşük iyi
    "sortino": (0.20, True),
    "smoothness": (0.10, False),  # günlük getiri otokorelasyonu: pürüzsüz fiyat şüpheli
}
RISK_WINDOW_DAYS = 252

# Yatırımcı & akış: testte zayıf öngörücü (akış geçmiş getiriyi kovalıyor),
# bu yüzden düşük ağırlık; büyük çıkışlar ayrıca ceza olarak işlenir.
INVESTOR_METRICS = {
    "aum_growth_1m": 0.50,   # 1 aylık büyüklük değişimi
    "flow_3m_ratio": 0.50,   # 3 aylık net akış / büyüklük
}

# Risksiz faiz: None ise para piyasası fonlarının günlük medyan getirisi
# (zamanla değişen, TLREF'e yakın) kullanılır. Sabit vermek için ör. 0.40.
RISK_FREE_RATE = None
RISK_FREE_FALLBACK = 0.40

# ------------------------------------------------------------- cezalar
# Kategori içi 1Y getiri anomalisi: robust z = (r - medyan) / IQR.
# Pürüzsüz ama kategorisinin çok üstünde getiri yazan fonlar (ör. Eylül 2026
# Tera Portföy fonları) risk metriklerinde "kusursuz" göründüğü için eklendi.
ANOMALY_Z_THRESHOLD = 3.0
ANOMALY_PENALTY_PER_Z = 2.0
ANOMALY_MAX_PENALTY = 15.0

# Yatırımcı sayısı cezası (üst sınır: yatırımcı < eşik -> puan)
INVESTOR_PENALTIES = [(100, 15), (500, 10), (1000, 5)]

# Net nakit çıkışı / büyüklük oranı (%) -> ceza puanı (ham skorun yarısı düşülür)
OUTFLOW_PENALTIES = [(-30, 8), (-20, 5), (-10, 3), (-5, 1)]

# "relative": notlar kategori içi dağılımla verilir (Morningstar benzeri
# %10 / %22.5 / %35 / %22.5 / %10). "absolute": sabit eşikler (85/75/65/55).
RATING_MODE = "relative"

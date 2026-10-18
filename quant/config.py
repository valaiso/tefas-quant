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

# ------------------------------------------------------------- GÜÇLÜ AL
# A+ / GÜÇLÜ AL yalnızca şu şartların hepsini sağlayan fonlara verilir; diğer
# kategori üst %10 fonları A / AL olur. Backtest (Ara 2023 – Eyl 2026, nitelikli
# fonlar hariç): ayda ~60 yerine ~24 fon, 6A'da kategori medyanını geçme %63 ->
# %70, 1Y'de %65 -> %72, 1 yılda %20'den fazla kaybettiren A+ oranı %0,25 -> %0.
STRONG_BUY = {
    "top_percentile": 95,     # kategori içi yüzdelik > 95 (üst %5)
    "min_history_days": 252,  # en az 1 yıllık fiyat geçmişi
    "min_investors": 1000,
    "min_aum": 100e6,         # en az 100 mn ₺ büyüklük
    "streak_months": 2,       # önceki 2 ay sonunda da A veya A+
}

# ------------------------------------------------------------- kurucu riski
# Bir portföy şirketinin halka açık fonlarının en az %30'u (en az 3 fon)
# işleme kapalı / çökmüş / fiyatı durmuşsa, şirketin kalan fonları işaretlenir,
# ceza alır ve notu İZLE'nin (B) üstüne çıkamaz. Ekim 2026'da Tera, Pardus,
# A1 Capital, Hedef, Atlas ve Bulls fonları grup halinde durdu; aynı kurucunun
# işlem gören fonları da sıçrama (spillover) riski taşır.
FOUNDER_RISK = {"min_share": 0.30, "min_funds": 3, "penalty": 10.0, "max_grade": "B"}

# ------------------------------------------------------------- risk bayrakları
# Point-in-time test (Eki 2024 – Eyl 2026, 24 ay, ~28 bin fon-ay gözlemi):
# * Son 3 ayda tepeden kategorisinden 10 puandan fazla düşüş: sonraki 1 yılda
#   kategoriye göre ~−4 puan, 1 yılda >%20 kaybettirme oranı ~5 kat -> küçük ceza.
# * Kuyruk riski (son 1 yılın en kötü %5 günlerinin ortalaması kategorinin en
#   kötü %10'unda): büyük kayıp oranı ~5 kat -> GÜÇLÜ AL engeli.
# * Sıcak para (1 ayda büyüklüğün %30'undan fazla net giriş): büyük kayıp oranı
#   ~3 kat -> GÜÇLÜ AL engeli.
# * Yoğunlaşma (yatırımcı azalırken para girişi, ör. TMG): sonraki getiriyi
#   düşürmedi -> ceza yok, yalnızca bilgi notu.
RISK_FLAGS = {
    "drawdown_rel_points": 10.0,   # son 3 ay tepeden düşüş, kategori medyanı + bu kadar puan
    "drawdown_penalty": 3.0,
    "tail_quantile": 0.10,         # CVaR %5 kategorinin en kötü %10'u
    "hot_money_flow_pct": 30.0,    # 1 aylık net giriş / büyüklük
    "concentration_investor_pct": -2.0,  # bilgi notu: 1A yatırımcı değişimi bunun altında
    "concentration_flow_pct": 5.0,       # ... ve 1A net giriş bunun üstünde
}

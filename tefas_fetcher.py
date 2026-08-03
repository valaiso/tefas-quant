import time
import random
import requests
from requests.exceptions import RequestException

# ==========================================
# 4. CHUNK & 5. WORKER AYARLARI
# ==========================================
MAX_WORKERS = 3          # 8 yerine 2-3 worker (TEFAS saldırı tespitini engeller)
CHUNK_DAYS = 30          # 90 gün yerine 30 günlük daha küçük parçalar

# ==========================================
# 1. EXPONENTIAL BACKOFF & 2. RETRY & 6. RANDOM BEKLEME
# ==========================================
def make_resilient_request(url, payload, max_retries=5):
    """
    Hata aldığında pes etmeyen, katlanarak bekleyen (Exponential Backoff)
    ve rastgele gecikme ekleyen dayanıklı istek fonksiyonu.
    """
    backoff_delays = [10, 30, 60, 90, 180]  # Saniye cinsinden bekleme süreleri
    
    for attempt in range(max_retries):
        try:
            # 6. RANDOM BEKLEME: Her istek öncesi trafiği doğal göstermek için insansı gecikme
            jitter = random.uniform(0.8, 1.6)
            time.sleep(jitter)
            
            # TEFAS API İstiği
            response = requests.post(url, data=payload, timeout=20)
            
            if response.status_code == 200:
                return response.json()
            
            print(f"⚠️ Sunucu HTTP {response.status_code} döndürdü. Yeniden deneniyor... ({attempt + 1}/{max_retries})")

        except (RequestException, Exception) as e:
            # RemoteDisconnected / Connection Aborted hataları burada yakalanır
            wait_time = backoff_delays[min(attempt, len(backoff_delays) - 1)]
            print(f"\n❌ Bağlantı Kesildi: {e}")
            print(f"⏳ {wait_time} saniye bekleniyor... (Deneme {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
            
    print("🚨 Maksimum deneme sayısına ulaşıldı, bu parça atlanıyor veya sonra tekrar denenecek.")
    return None

# ==========================================
# 3. SON BAŞARILI TARİHTEN DEVAM ET (CHECKPOINT)
# ==========================================
def sync_fund_history(db_connection, fund_code, start_date, end_date):
    """
    Veritabanını kontrol eder, eğer bu fon için son çekilen tarih varsa 
    500 günü baştan çekmez, kaldığı günden (örn. 301. gün) devam eder.
    """
    # Veritabanından bu fonun en son hangi tarihe kadar indirildiğini sorgula
    last_saved_date = get_last_downloaded_date_from_db(db_connection, fund_code)
    
    if last_saved_date:
        print(f"📌 {fund_code} için son başarı tarihi: {last_saved_date}. Buradan devam ediliyor...")
        effective_start_date = last_saved_date
    else:
        effective_start_date = start_date

    # 30'ar günlük parçalar halinde veri çekme döngüsü
    # (Örnek mantık: effective_start_date -> end_date arası CHUNK_DAYS kadar ilerle)
    # Her 30 günlük parça başarılı bittiğinde veritabanına checkpoint kaydet:
    # save_checkpoint_to_db(db_connection, fund_code, current_chunk_end_date)
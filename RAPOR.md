# TEFAS Quant — İnceleme, Hata Ayıklama ve Karşılaştırma Raporu

*Tarih: 18.10.2026 · Kapsam: `main` @ 79aa196 + çalışma kopyasındaki değişiklikler*

---

## 1. Özet

TEFAS Quant; TEFAS'taki ~1.060 fonun günlük fiyatlarını SQLite'a toplayan, Sharpe/Sortino/MDD gibi
metrikler hesaplayan, fonları **kategori içinde** 0–100 arası puanlayıp AL/İZLE/UZAK DUR sinyali
üreten ve bunu bir Streamlit panelinde gösteren bir proje.

**Fikir sağlam, uygulamada ise skorun güvenilirliğini bozan ciddi hatalar vardı:**

| # | Bulgu | Etkisi | Durum |
|---|---|---|---|
| 1 | Skorlar 1260 gün geriye tarihlenip kaydediliyordu (**look-ahead**) | Backtest'teki %86 isabet ve Sharpe 2.29 gerçek değil | ✅ Düzeltildi |
| 2 | Fiyat tablosunda **223.200 tekrarlı satır** ve **24.522 adet 0 fiyat** vardı | "30 günlük getiri" gibi pencereler yanlış dönemi ölçüyordu | ✅ Kodda düzeltildi, DB temizleme betiği hazır |
| 3 | Pencereler satır sayısıyla ölçülüyordu (365 satır = ~1,45 yıl, 1825 satır = ~7,2 yıl) | 1Y/3Y/5Y getirileri yanlış etiketliydi | ✅ Düzeltildi |
| 4 | "Gizli Cevherler" bölümü fon koduna göre **rastgele uydurulmuş** varlıklar gösteriyordu | Gerçek analiz gibi duran sahte veri | ✅ Kaldırıldı |
| 5 | Modelin zirvesindeki **TP2 (1.) ve TLY (4.)** Eylül 2026'da tasfiyeye girdi | Model, kredi/likidite riskini göremiyor | ⚠️ Tasarım sorunu (bölüm 5) |
| 6 | Temiz kurulumda uygulama `st.dataframe`'de çöküyordu (pyarrow ↔ NumPy) | Streamlit Cloud / yeni bilgisayarda açılmıyor | ✅ Düzeltildi |
| 7 | GitHub Actions her 20 dakikada **var olmayan** `collector.py`'yi çalıştırıyordu | Her çalışmada hata | ✅ Düzeltildi |

**İyi haber:** Skorun fiyata dayalı kısmını (performans + risk) geleceği görmeden, her ay yalnızca o
güne kadarki veriyle yeniden hesapladım. Kategori içinde gelecek 3 ayın getirisiyle anlamlı ve pozitif
bir ilişki var (ortalama rank IC ≈ **0,19**, 33 ayın %88'inde pozitif, t ≈ 6,4). Yani temel fikir
işe yarıyor gibi duruyor; yalnızca ölçüm altyapısının dürüst olması gerekiyordu.

---

## 2. Sistem Nasıl Çalışıyor?

```
TEFAS (tefas-crawler)          Fundfy API              fvt.com.tr API
  fetch_history.py              update_fund_flow_       sync_fvt_metrics.py
  fetch_recent_prices.py        metrics.py
        │                            │                        │
        ▼                            ▼                        ▼
  fund_daily_prices          fund_flow_metrics        fund_external_metrics
        │                    fund_aum_history         (AUM, yatırımcı, akış,
        │                    fund_cash_flow_history    ücret, stopaj)
        ▼
  analysis_engine.py + metrics.py  ──►  fund_metrics (Sharpe, Sortino, MDD, VaR, beta, alfa…)
        │
        ▼
  scoring.py + app/services/scoring_engine.py  ──►  fund_scores (skor, harf notu, sinyal)
        │
        ▼
  app.py (Streamlit)  ◄──  app/services/ranking.py, backtest/engine.py
```

### Skor formülü

Her kategori için ayrı ayrı:

| Bileşen | Ağırlık | İçerik |
|---|---|---|
| Performans | %35 | 1A %10, 2A %15, 3A %20, 6A %25, 1Y %20, 3Y %5, 5Y %5 getirilerinin kategori içi yüzdelikleri |
| Risk | %25 | Volatilite %25, MDD %25, Sharpe %20, Sortino %15, Calmar %10, Beta %5 (mutlak eşikler) |
| Yatırımcı / nakit akışı | %20 | Yatırımcı sayısı %55, 1A yatırımcı büyümesi %15, akış/AUM %30 |
| Maliyet | %10 | Yönetim ücreti (kategori içi, en az 50 puan) |
| Portföy kalitesi | %10 | AUM eşikleri + alfa |

Sonra: yatırımcı sayısı cezası (−15…0), nakit çıkışı cezası, güven ayarı `(güven−50)/10` ve yatırımcı
istikrar bonusu (−5…+3). Notlar: ≥85 A+/GÜÇLÜ AL, ≥75 A/AL, ≥65 B/İZLE, ≥55 C/ZAYIF, altı D/UZAK DUR.

---

## 3. Bulunan Hatalar (Ayrıntılı)

### 3.1 Kritik — look-ahead (geleceği görme) hatası
`scoring.py`'deki son commit (79aa196) skorları **en son fiyat tarihinden 1260 gün önceye** tarihliyordu
(`score_date = max_price_date - 1260 gün` → 2023-03-20). Skorlar 2026 Ağustos verisiyle hesaplanıyor ama
2023'te verilmiş gibi kaydediliyordu. Backtest bu skorları 2023'te "alıp" sonrasındaki getirileri
ölçüyordu, yani sonucu önceden bilerek sınanmış oluyordu.

Ölçtüklerim:
- Bu "2023" skorlarıyla 2023→2026 getirisi arasındaki korelasyon **+0,35**. Bu bir sızıntı işareti.
- Aynı skorlarla 6 ay ve 1 yıllık ileri getiri ilişkisi **negatif** (−0,15 / −0,08). Çünkü skor
  2023'ün değil 2026'nın durumunu ölçüyor.
- Panelde gösterilen **%86 isabet oranı**, TL'nin değer kaybı yüzünden neredeyse her fonun nominal
  olarak yükselmesinden geliyor. Bir kıyas noktası olmadan anlamsız.

Ayrıca bu yüzden "Hızlı Güncelleme" düğmesi yeni skorları 2023 tarihine yazıyordu. Dashboard ise
`MAX(date)` = 2026-08-23'ü okuduğu için **eski skorları göstermeye devam ediyordu**.

**Düzeltme:** Skor tarihi artık hesaplamada kullanılan son fiyat günü. Backtest'e "aynı tarihlerde tüm
fon evreninin ortalaması" ve "evrene göre fazla getiri" eklendi. 2023-03-20 tarihli sızıntılı satırları
`cleanup_db.py` siliyor.

> Sonuç: Backtest sayfası şu an dürüstçe "yeterli ileri veri yok" diyor, çünkü elde yalnızca Ağustos
> 2026 skorları var. Gerçek bir backtest için tarihsel skorların o günün verisiyle üretilmesi gerekiyor
> (bölüm 7, madde 1).

### 3.2 Kritik — veri bütünlüğü
- `fund_daily_prices` tablosunda `(fund_id, date)` için tekillik kısıtı yok. 979.487 satırın **223.200'ü
  tekrar**; bazı günlerde aynı fonun 7 kopyası var (2026-04'ten itibaren yoğun).
- **24.522 adet 0 fiyat** var (yalnızca 2026-08-05'te 338 tane).
- 1.044 fonda **2026-08-05 → 2026-08-31 arasında 26 günlük boşluk** var.
- Skorlama `prices[-30]` gibi satır sayısıyla geri gittiği için bunların hepsi getiri, volatilite ve
  backtest'teki elde tutma süresini kaydırıyordu.

**Düzeltme:** `scoring.py` ve backtest motoru artık her gün için tek ve pozitif fiyat kullanıyor.
`cleanup_db.py` tabloyu temizleyip `UNIQUE (fund_id, date)` indeksi ekliyor (önce `tefas.db.bak` yedeği alır).

### 3.3 Yüksek — dönem uzunlukları
`r_365 = prices[-1]/prices[-365]` aslında ~1,45 yılı ölçüyordu (yılda ~252 işlem günü var).
`r_1825` (5Y) ~7,2 yıl gerektirdiği ve veride en fazla 5 yıl olduğu için **hiç hesaplanmıyor**, hep
3Y'ye düşüyordu. Artık 21/42/63/126/189/252/756/1260 işlem günü kullanılıyor; yıllıklandırma da 252.

### 3.4 Yüksek — panelde yanlış veya sahte bilgi
- **Sahte portföy:** `fund_stock_holdings` boş olduğunda `hashlib.md5(fon_kodu)` tohumuyla rastgele
  "Varlık A/B/C/D" ağırlıkları, DCF iskontoları ve "Fair Value Skoru" üretiliyordu. Kaldırıldı; artık
  "veri yok" yazıyor.
- **Boş çubuklar:** "Kalite Skoru" ve "Nakit Akışı" çubukları hep **0** görünüyordu (`quality_score` /
  `cashflow_score` anahtarları aranıyordu, oysa kayıtlı anahtarlar `portfolio_score` / `investor_score`).
- **Yanlış sıralama:** Fon Havuzu "Top %X" metnine göre alfabetik sıralanıyordu ("Top %10" < "Top %2").
- **Eski metrikler:** Fon detayında `fund_metrics` için ilk (en eski) satır alınıyordu; artık en güncel satır.
- "Geçmiş Gün" tekrarlı satırları da sayıyordu (bir fonda 4.094 "gün" vardı).

### 3.5 Orta — birim ve tanım hataları
- MDD yedek hesabı yüzde (15), `fund_metrics` ise ondalık (0,15) kullanıyordu. `_score_drawdown(x) =
  100 − 150x` olduğu için yedeğe düşen fon risk puanından 0 alıyordu. Ondalığa çevrildi.
- **Nitelikli fon tespiti:** "ÖZEL" anahtar kelimesi, herkese açık **Özel Sektör Borçlanma Araçları**
  fonlarını (AYR, GUB, YBS, TBV…) nitelikli sayıyordu. "Nitelikli fonları hariç tut" seçilince bu fonlar
  listeden düşüyordu. Düzeltildi.

### 3.6 Kurulum ve otomasyon
- `requirements.txt` pyarrow'u sabitlemiyordu. Temiz kurulumda pyarrow ≥18 geliyor, bu da NumPy 2
  istiyor; `numpy==1.26.4` ile **her tablo çöküyor**. Ayrıca `requests` ve `SQLAlchemy` eksikti.
  Eklendi (`pyarrow==17.0.0`).
- `.github/workflows/update.yml` 20 dakikada bir var olmayan `collector.py`'yi çalıştırıyordu. Artık hafta
  içi 21:00'de (TSİ) `fetch_recent_prices → analysis_engine → scoring` sırasını çalıştırıyor. **Uyarı:**
  `tefas.db` ~70 MB; her gün commit'lemek repo geçmişini hızla şişirir (bölüm 7).

### 3.7 Düzeltilmeyen, bilinmesi gerekenler
| Konu | Açıklama |
|---|---|
| Risksiz faiz %20 | `metrics.py` RF=0,20 kullanıyor, `config/settings.py` yok. 2024–26'da TL politika faizi bunun çok üstünde olduğu için para piyasası fonlarının Sharpe'ı şişiyor. |
| Benchmark | `analysis_engine.py` benchmark'ı **tüm fonların fiyat ortalaması** olarak alıyor. Fiyat seviyeleri farklı ve fon giriş/çıkışları ortalamayı sıçratıyor, bu yüzden beta/alfa/IR anlamsız. Kategori ortalaması getirisi veya BIST100/TLREF/altın kullanılmalı. |
| Calmar | MDD ≈ 0 olan fonlarda 97.821 gibi değerler çıkıyor (puanlamada 100'e kırpılıyor). |
| Fundfy nakit akışı | `positive_ratio × 1.000.000.000 × 0,2` her fona yapay olarak ~200 milyon TL "akış" ekliyor. Şimdilik yalnızca fvt verisi olmayan 2 fonda kullanılıyor. |
| `fund_info_metrics` | Tüm fonlarda sabit yer tutucu (ücret 2,0, AUM 0). |
| Kategoriler | "Yatırım Fonu" / "Yatirim Fonu" / "Diğer" çöp kutusu kategoriler (226 fon). Serbest fonlar, para piyasasıyla aynı kefeye düşebiliyor. |
| Ölü kod | `app/api/scoring_router.py` (tanımsız `ranked_df` ve olmayan sınıflar), `src/*` (boş tarayıcılar), `modify_backtest.py` (sözdizimi hatası), `scoring_engine_backup.py`, `app.py.backup`, `app.py.before_cache`, 0 baytlık `'@'`, `findstr`, `python`, `500_000_000` dosyaları, `database/fonlar.db`. |
| Bayat veri | Son fiyat 31.08.2026, bugün 18.10.2026. Güven skorundaki "güncellik" bileşeni tüm fonlarda tabanda. |

---

## 4. Dürüst (point-in-time) test: skor işe yarıyor mu?

Bunun için ayrı bir betik yazdım, projeye eklemedim. Ekim 2022'den Nisan 2026'ya kadar her ~21 işlem
gününde şunları yaptım: yalnızca o güne kadarki temiz fiyatlarla performans ve risk bileşenlerini
(projedeki `scoring_engine` fonksiyonlarının aynısı) kategori içinde hesapladım ve sonraki 63 işlem
gününün getirisiyle karşılaştırdım. En az 10 fonu olan kategoriler alındı.

| Ölçü | Aynı gün giriş | T+2 giriş (ileri fiyatlama) |
|---|---|---|
| Ortalama rank IC (kategori içi) | 0,198 | 0,189 |
| IC > 0 olan ay oranı | %88 | %88 |
| IC t-istatistiği | 7,4 | 6,4 |
| En üst %20'nin kategori ortalamasına göre fazla getirisi (3 ay) | +%1,65 | +%1,41 |
| En alt %20'nin fazla getirisi (3 ay) | −%0,27 | ~%0 |

**Yorum:** TEFAS'ta kategori içi momentum/kalite etkisi belirgin. Akademik literatür bu konuda
temkinli: Carhart (1997) ABD'de süreklilik büyük ölçüde hisse momentumundan geliyor diyor, Choi & Zhao
(2020) bunun 1994 sonrası örneklem dışında kaybolduğunu buluyor, Türkiye çalışmaları da genel bir
süreklilik bulamıyor. Bu yüzden sonucu iyimser okumamak gerekiyor:
- **Hayatta kalma yanlılığı:** Veritabanında yalnızca bugün TEFAS'ta olan fonlar var; kapanan fonlar yok.
- **Kategoriler kaba:** Örneğin "Değişken" kategorisinde çok farklı fonlar bir arada.
- **Fiyat yumuşatma:** Para piyasası, borçlanma ve serbest fonlarda fiyatlar yumuşatılmış olabilir.
  Bu hem momentumu şişirir hem de riski olduğundan düşük gösterir (bkz. bölüm 5).
- Stopaj ve vergi hesaba katılmadı.

---

## 5. En önemli tasarım dersi: Tera Portföy vakası

Modelin şu anki sıralamasında:

| Sıra | Fon | Final skor | Sinyal |
|---|---|---|---|
| 1 | **TP2** — Tera Portföy Para Piyasası (TL) | 95,8 | GÜÇLÜ AL |
| 4 | **TLY** — Tera Portföy Birinci Serbest | 92,4 | GÜÇLÜ AL |

Haberlere göre **17 Eylül 2026'da SPK kararıyla Tera Portföy'ün beş fonunda (TLY, T3B, DOH, TP2, TLV)
işlemler durduruldu ve tasfiye süreci başladı.** TLY, THF ve DOH'ta iade ödemelerinde temerrüt oluştu.
(`portföy-analiz` projendeki "Treat defaulted THF and TP2 as fixed…" commit'i de bununla uyumlu.)

**Neden olabildi?** Model sadece fiyat serisine bakıyor. Bu fonlar her gün düzenli ve pürüzsüz bir
getiri yazıyordu: düşük volatilite, ~0 MDD, yüksek Sharpe/Calmar, güçlü momentum ve yatırımcı/AUM
büyümesi. Risk bileşeni bu tablodan 96–100 puan alıyor. Oysa pürüzsüz fiyat, değerlemesi zor veya
likit olmayan varlıkların bir belirtisi olabilir. Sorun fiyatta değil; bilanço, likidite ve yönetici
tarafında birikiyordu.

Bu açığı kapatmak için piyasadaki iki örnek proje doğrudan fikir veriyor:
- **turkish-fund-liquidity-monitor:** README'sine göre aynı Eylül 2026 krizinde TLY'nin likidite
  tamponunun, işlemler durmadan 7 iş günü önce sıfırın altına indiğini KAP portföy raporlarından
  gösteriyor. PHE ve PBR'de bilanço sinyalleri ~4 hafta önceden görünmüş.
- **turkeyFundLens:** "Stres görünümü" var. Toplu nakit çıkışı (run) tespiti, yoğun girişten yoğun
  çıkışa dönen fonlar, pay sayısı ve yatırımcı sayısı donduğu hâlde fiyatı oynayan fonlar ve kurucu
  bazında toplulaştırma yapıyor.

Önerilen ek kurallar:
1. **Pürüzsüzlük cezası:** Günlük getirilerin 1. dereceden otokorelasyonu çok yüksek ve volatilite çok
   düşükse "risk" puanına üst sınır koy. Ya da Getmansky–Lo–Makarov düzeltmesiyle volatiliteyi yeniden hesapla.
2. **Kategori anomali kontrolü:** Para piyasası fonu kategori medyanının çok üstünde getiri yazıyorsa
   bunu ödül değil kırmızı bayrak say.
3. **Likidite/akış stresi:** Akış/AUM'daki ani kopuşlar ve pay sayısının donması.
4. **Kurucu yoğunlaşması:** Aynı portföy şirketinin birden çok fonunda eş zamanlı sinyal.
5. **Olay filtresi:** KAP'ta "işlem durdurma / temerrüt / değerleme sıklığı değişikliği" bildirimi
   gelen fonu otomatik olarak UZAK DUR yap.

---

## 6. Benzer projelerle karşılaştırma

| Proje / Ürün | Ne yapıyor | TEFAS Quant'a göre |
|---|---|---|
| **tefas-crawler** (burakyilmaz321, ~114★) | TEFAS verisi çeken Python kütüphanesi | Senin veri kaynağın. TEFAS 2026'da Next.js tabanlı yeni platforma geçti; pytefas'ın README'sine göre eski HTML tabanlı çözümler bundan etkilendi. Verinin 31.08'de durmasının bir sebebi bu olabilir (doğrulanmadı). |
| **pytefas** (mirzazad, ~20★) | TEFAS'ın yeni resmî JSON uçları; ~28 günlük parçalama, hız sınırı yönetimi (~6 istek/dk), 50+ varlık dağılımı kolonu | **Taşınmaya en güçlü aday.** Portföy dağılımını (hisse/tahvil/repo/altın) doğrudan verdiği için sahte "Gizli Cevherler" bölümü gerçek veriyle yapılabilir. |
| **turkeyFundLens** (hakyemezi) | AUM'u piyasa etkisi ve yatırımcı akışı olarak ayrıştırıyor; KMeans ile portföy DNA sınıflandırması; stres sinyalleri; Streamlit + günlük statik site | Senin "Yatırımcı/Nakit" bileşeninin olgun hâli. Dönemleri senin yeni düzeltmen gibi takvim günü yerine **işlem aralığıyla** sayıyor, 0 fiyatlı günleri yayımlanmamış kabul ediyor. Kategori yerine portföy kümelemesi, senin kaba kategori sorununu çözer. |
| **turkish-fund-liquidity-monitor** (Raknero) | TEFAS + KAP portföy PDF'leri ile likidite izleme; Eylül 2026 krizi vaka çalışması | Senin modelinde hiç olmayan kredi/likidite boyutu. |
| **fonliman**, **tefas-fon**, **fonbot-ai** | Kendi sunucunda çalışan takip panelleri, KAP+TEFAS karşılaştırma, AI ajanlarına aylık dağılım önerisi | Benzer hedef kitle. Çoğu skor yöntemini açıklamıyor. |
| **Fintables / FVT / Fonbul** | Ticari fon karşılaştırma; FVT Skoru, nakit giriş/çıkış listeleri | FVT'nin skor yöntemi kamuya açık değil. Sen zaten fvt'den yatırımcı, ücret ve akış verisi çekiyorsun (kullanım koşullarını kontrol et). |
| **Morningstar Rating** | Kategori içi, riske göre düzeltilmiş getiri (beklenen fayda; aşağı yönlü oynaklığa daha çok ceza); 3/5/10 yıllık ağırlıklı; dağılım %10/22,5/35/22,5/10 | Senin "kategori içi yüzdelik" yaklaşımının altın standardı. Farklar: (a) Morningstar mutlak eşik yerine **tamamen göreli** çalışıyor, (b) en az 3 yıl geçmiş istiyor, (c) yıldızları kesin dağılımla dağıtıyor. Sende 1.033 fonun 553'ü "UZAK DUR", çünkü mutlak eşikler kullanılıyor. |

**Projenin güçlü yanları:**
- Kategori içi karşılaştırma (doğru çerçeve).
- Çok kaynaklı veri: TEFAS + Fundfy + FVT.
- Skorun açıklanabilirliği (`breakdown_json`).
- Güven skoru fikri.
- Nitelikli fon ayrımı.
- Point-in-time testte anlamlı sinyal.

**Zayıf yanları:**
- Fiyat dışında risk görmüyor (kredi, likidite).
- Veri hattında doğrulama ve tekillik yok.
- Mutlak eşiklerle kategori yüzdeliği karışık kullanılıyor.
- Test yok.
- İki ayrı (ve tutarsız) skorlama yolu var: `scoring.py` ve `generate_history_scores.py` /
  `backtest/historical_scoring.py`.
- Backtest gerçek bir portföy simülasyonu değil: tüm sinyallerin ortalaması alınıyor, ağırlık, nakit ve
  yeniden dengeleme yok.

---

## 7. Yol haritası (öncelik sırasıyla)

1. **Gerçek tarihsel skor ve backtest.** `scoring.py`'deki hesaplamayı `as_of_date` parametresi alan tek
   bir fonksiyona dönüştür. Aylık tarihlerde yalnızca geçmiş veriyle skor üret ve `fund_scores`'a doğru
   tarihle yaz. Backtest'i "her ay kategori başına en iyi N fonu eşit ağırlıkla al, T+2 fiyatla gir,
   stopaj düş" şeklinde portföy simülasyonuna çevir. Kıyas olarak kategori ortalaması, TLREF/para
   piyasası ve BIST100 kullan.
2. **Veri katmanı:** `cleanup_db.py`'yi çalıştır; tekillik indeksi kalıcı olsun. Kaynağı pytefas veya
   TEFAS'ın yeni uçlarına taşı. Günlük doğrulama ekle: 0 fiyat, %±30 üstü günlük hareket, boşluklar.
3. **Risk modeli:** Bölüm 5'teki pürüzsüzlük, anomali, akış stresi ve KAP olay kurallarını ekle.
   RF'yi TLREF serisinden al. Benchmark'ı kategori ortalaması yap.
4. **Göreli notlama:** Harf notlarını mutlak eşik yerine kategori içi dağılımla ver (Morningstar gibi
   %10/22,5/35/22,5/10).
5. **Kategoriler:** "Diğer/Yatırım Fonu" kovalarını TEFAS şemsiye türüyle ya da portföy dağılımı
   kümelemesiyle (turkeyFundLens yaklaşımı) yeniden sınıflandır.
6. **Mühendislik:** Ölü kodu ve 0 baytlık dosyaları temizle. `pytest` ile metrikler ve skor için birim
   testleri yaz. `tefas.db`'yi git'ten çıkar (Git LFS, GitHub Release ya da artifact). Streamlit'te
   `@st.cache_data` kullan.

---

## 8. Bu oturumda yapılan değişiklikler

| Dosya | Değişiklik |
|---|---|
| `scoring.py` | Look-ahead tarih kaydırması kaldırıldı; tekil ve pozitif fiyat sorgusu; işlem günü pencereleri; 252 yıllıklandırma; MDD birimi; "ÖZEL SEKTÖR" nitelikli istisnası |
| `backtest/engine.py` | Tekrarlı ve 0 fiyat temizliği; evren ortalaması ve fazla getiri metrikleri |
| `app.py` | Sahte portföy kaldırıldı; breakdown anahtarları; sayısal sıralama; en güncel metrik satırı; DISTINCT gün sayısı; takvim günüyle kesme kaldırıldı; backtest kıyas metrikleri |
| `requirements.txt` | pyarrow 17 sabitlendi; requests ve SQLAlchemy eklendi |
| `.github/workflows/update.yml` | Gerçek betikler, günlük tek çalışma, Python 3.11, `contents: write` |
| `cleanup_db.py` (yeni) | Yedek al → tekrar ve 0 fiyat sil → UNIQUE indeks → look-ahead skorları sil → nitelikli bayrağını düzelt |

**Doğrulama:** Veritabanının bir kopyasında `cleanup_db.py` → `scoring.py` → Streamlit `AppTest` ile 7
sayfanın hepsi hatasız açıldı. Kalite ve yatırımcı çubukları artık dolu, sıralama doğru, backtest
dürüstçe "yeterli ileri veri yok" diyor. **Gerçek `tefas.db`'ye dokunulmadı; hiçbir şey commit'lenmedi.**

---

### Kaynaklar
- [tefas-crawler (gittrend)](https://gittrend.io/repo/burakyilmaz321/tefas-crawler) · [pytefas](https://github.com/mirzazad/pytefas) · [GitHub "tefas" konusu](https://github.com/topics/tefas)
- [turkeyFundLens](https://github.com/hakyemezi/turkeyFundLens) · [turkish-fund-liquidity-monitor](https://github.com/Raknero/turkish-fund-liquidity-monitor) · [fonlar-mcp](https://github.com/maku-cpu/fonlar-mcp)
- [Fintables fon karşılaştırma](https://fintables.com/fon-karsilastirma?funds=TFE) · [FVT yatırım fonları](https://fvt.com.tr/fonlar/yatirim-fonlari) · [Fonbul](https://apps.apple.com/tr/app/fonbul/id6469306617)
- [Morningstar Rating for Funds — metodoloji](https://morningstar.com/content/cs-images/v3/assets/blt9415ea4cc4157833/blt4746ec2633987fb2/67819c62694c4c0ed070ba0a/Morningstar_Rating_for_Funds.pdf)
- [Carhart (1997), On Persistence in Mutual Fund Performance](https://www.afajof.org/page/Top50Cited) · [Choi & Zhao, NBER w26707](https://www.nber.org/papers/w26707)
- [Performance of Turkish mutual funds (Bilgi Ü.)](https://openaccess.bilgi.edu.tr/items/4ed11cb4-2357-466f-97a8-3f9bba7afc23) · [İlhan — Gelişim Ü.](https://avesis.gelisim.edu.tr/yayin/8411879d-6ec1-41a9-b169-4358f7d5a674/performance-measurement-of-voluntary-based-pension-funds-in-turkey-case-analysis-on-a-specific-pension-company)
- Tera Portföy: [Habertürk](https://www.haberturk.com/ekonomi/tera-portfoy-den-spk-karari-sonrasi-aciklama-5-fon-icin-tasfiye-sureci-3913262) · [Bloomberg HT](https://www.bloomberght.com/tera-portfoyden-tasfiye-sureci-aciklamasi-3788705) · [Foreks — temerrüt](https://www.foreks.com/haber/detay/6aac334324008d7d43733535/PICNEWS/tr/tera-portfoy-un-uc-fonunda-daha-iade-odemelerinde-temerrut-olustu-17-09-26/) · [CNBCE](https://www.cnbce.com/borsa/tera-portfoyden-spk-karari-sonrasi-yeni-aciklama-5-fonda-tasfiye-sureci-tera-portfoyde-kritik-gelisme-5-fonda-islemler-durduruldu-tasfiye-sureci-basladi-h37488)

*Bu rapor yazılımın teknik incelemesidir; yatırım tavsiyesi değildir.*

---

## 9. Uygulanan güncellemeler (18.10.2026, 2. oturum)

| Adım | Sonuç |
|---|---|
| `cleanup_db.py` gerçek DB'de çalıştırıldı | 223.200 tekrarlı satır ve 24.522 adet 0 fiyat silindi, sızıntılı skorlar kaldırıldı, UNIQUE indeks eklendi. Yedekler: `tefas.db.bak`, `tefas.db.before_cleanup_20261018` |
| `fetch_recent_prices.py` yeniden yazıldı ve çalıştırıldı | 01.08–16.10.2026 arası 1.071 fon, 58.327 satır, hata yok. 26 günlük Ağustos boşluğu kapandı. Fon başına istek atıyor, upsert yapıyor |
| `sync_fvt_metrics.py` yeniden yazıldı | AUM, yatırımcı, ücret, stopaj, `islem` ve `serbest` bayrakları. 1H/1A net akış ve 1A yatırımcı/AUM büyümesi FVT'nin 30 günlük pay adedi geçmişinden hesaplanıyor. Fundfy 429 (istek sınırı) döndürdüğü için devre dışı |
| `fund_attributes.py` (yeni) | 222 fon "Yatırım Fonu/Diğer" kovasından FVT kategorisine taşındı (209 fon "Serbest") |
| `config/settings.py` (yeni) | Risksiz faiz, bayatlık eşiği, anomali cezası ve notlama modu ayarları |
| `analysis_engine.py` | Benchmark artık kategori içi eşit ağırlıklı günlük getiri. Risksiz faiz, para piyasası fonlarının günlük medyan getirisi (zamanla değişen; son 1 yıl %46,5) ve her fonun kendi döneminin ortalaması |
| `scoring.py` | Fiyatı 7 günden eski fonlar skorlanmıyor: TLY, TP2, THF, DOH, TLV, PHE, PBR, DFI, HNC, GO2. Kategori içi 1Y getiri anomalisi cezası (robust z > 3; şu an 6 fon). Göreli notlama (%10/22,5/35/22,5/10). Eksik akış dönemlerinin ağırlığı diğerlerine dağıtılıyor |
| `app.py` | Skorlanmayan fonlar listesi, fon detayında dışlanma nedeni ve anomali uyarısı, son fiyat günü |
| `run_pipeline.py` (yeni) | `python run_pipeline.py` tüm hattı çalıştırır, `--skip-fetch` yalnızca metrik ve skor üretir |

**Yeni dağılım (16.10.2026, 1.055 fon):** GÜÇLÜ AL 111 · AL 238 · İZLE 365 · ZAYIF 238 · UZAK DUR 103

**Backtest uyarısı:** 1 aylık backtest, Ağustos 2026 skorlarıyla (eski kodla üretilmiş ama doğru
tarihli) %86 isabet veriyor. Ancak aynı tarihlerde fon evreni ortalaması %2,21, stratejininki %2,28;
yani **fazla getiri yalnızca +%0,07**. İsabet oranının tek başına neden yanıltıcı olduğunu bu sonuç
açıkça gösteriyor. Gerçek bir değerlendirme için tarihsel skorların o günün verisiyle üretilmesi gerekiyor
(bölüm 7, madde 1).

---

## 10. Yeni mimari (18.10.2026, 3. oturum)

> Bölüm 3–9'da adı geçen Streamlit uygulaması (`app.py`) ve eski betikler kaldırıldı. Proje artık
> Portföy Analiz'le aynı yapıda çalışan statik bir site.

```
TEFAS /api/funds (fiyat, pay, yatırımcı, büyüklük; tek istekte tüm fonlar, 28 günlük parçalar)
FVT (ücret, stopaj, işlem durumu; haftada bir)
        │  quant/fetch.py  → data/tefas.sqlite  (yalnızca son 3 yıl; git'e girmez, Actions cache'inde)
        ▼
quant/scoring.py   → metrikler, 5 bileşen, cezalar, göreli not   (ayarlar: quant/config.py)
        ▼
quant/export.py    → dist/data/*.json  (meta, funds, categories, haftalık fon geçmişi)
        ▼
index.html + assets/  → GitHub Pages
```

| Konu | Önce | Şimdi |
|---|---|---|
| Depodaki veri | `tefas.db` 76,5 MB, her gün commit'leniyordu | Depoda veri yok; ham veri Actions cache'inde. Yayın ~10 MB JSON |
| Geçmiş | 5 yıl, tekrarlı satırlar | **3 yıl**, her çalışmada budanıyor. 3Y getiri ağırlığı %10, 5Y kaldırıldı |
| Güncelleme | Her 20 dk (hatalı) / günlük commit | **İşlem günü akşamı tek derleme** (19:00 TR, atlanırsa 21:00); hafta sonu ve tatilde derleme yok |
| Veri kaynağı | tefas-crawler (fon başına istek) + Fundfy (429) + FVT | TEFAS resmî API (toplu) + FVT (haftalık) |
| Akış ve yatırımcı | FVT 30 günlük geçmiş | TEFAS pay adedi × fiyat; 1H / 1A / 3A akış ve 1A yatırımcı değişimi |
| Kategori | TEFAS dışı karışık adlar | TEFAS resmî şemsiye türleri; "Serbest" ünvandan alt sınıflara ayrıldı (Para Piyasası, Döviz, Hisse, Katılım, Kıymetli Madenler, Fon Sepeti, Çoklu Varlık) |
| Arayüz | Streamlit | Kurumsal statik site: Genel Bakış, Sıralama (filtre, sıralama, sayfalama), Fon Detayı (puan dökümü, grafik), Karşılaştır, Metodoloji; açık/koyu tema, mobil uyumlu |
| Skor geçmişi | Yok | `scores` tablosu her günün skorunu saklıyor; ileride gerçek (point-in-time) backtest için |

**Yerel çalıştırma**

```bash
pip install -r requirements.txt
python scripts/update.py          # artımlı güncelle + skorla + dist/ üret
python -m http.server 8000 -d dist
```

**Yayına almak için tek seferlik ayar:** GitHub → Settings → Pages → Source: **GitHub Actions**.
İlk çalıştırmada cache boş olduğu için 3 yıllık veri baştan çekilir (~10–15 dk).

---

## 11. Skor modeli v2 (18.10.2026)

Ağırlıklar ve alt metrikler, 3 yıllık TEFAS verisinde o günün verisiyle (point-in-time) yapılan testlere göre yeniden ayarlandı.
Test ayarları: Ekim 2024 – Temmuz 2026 arası 22 ay; her ay kategori içi sıralama, 3 aylık ileri getiri, T+2 giriş, ≥10 fonluk kategoriler.

| Metrik (kategori içi) | Rank IC | t | Pozitif ay |
|---|---|---|---|
| 1Y getiri | 0,255 | 10,2 | %95 |
| 6A getiri | 0,254 | 9,2 | %95 |
| Sharpe (1Y) | 0,229 | 9,3 | %100 |
| 1A getiri | 0,196 | 6,7 | %91 |
| Sortino (1Y) | 0,182 | 6,7 | %86 |
| 3A getiri | 0,171 | 5,2 | %86 |
| Maks. düşüş (yüksek = kötü) | −0,137 | −4,2 | – |
| Pürüzsüzlük (otokorelasyon) | −0,081 | −2,6 | – |
| Düşük yönetim ücreti | 0,068 | 5,5 | %91 |
| 1A büyüklük değişimi | 0,050 | 2,5 | %73 |
| 3A akış / büyüklük | 0,028 | 2,0 | %68 |
| 1A yatırımcı değişimi | 0,013 | 0,6 | %50 |
| Yatırımcı sayısı | −0,029 | −2,2 | – |

| Model | IC (tüm dönem) | IC 1. yarı | IC 2. yarı | Üst %20 fazla getiri (3A) |
|---|---|---|---|---|
| v1 (önceki) | 0,243 | 0,233 | 0,254 | +%1,20 |
| Taslak öneri (Perf 40 / Risk 15 / Akış 25 / Maliyet 10 / Portföy 10) | 0,237 | 0,233 | 0,240 | +%1,35 |
| **v2** | **0,273** | **0,283** | **0,262** | **+%1,51** |

**v2:** Performans %40 (1A 10, 3A 20, 6A 35, 1Y 35) · Risk %30 (Sharpe 40, maks. düşüş 30, Sortino 20,
pürüzsüzlük 10; son 252 gün) · Maliyet %15 (yönetim ücreti) · Yatırımcı & akış %10 (1A büyüklük değişimi 50,
3A akış 50) · Portföy %5 (büyüklük). Tüm alt metrikler kategori içi yüzdelik. Cezalar (az yatırımcı, nakit çıkışı,
getiri anomalisi), veri güveni ayarı ve göreli notlama aynen korundu.

**Sınırlar:** Test dönemi kısa (22 ay, örtüşen 3 aylık pencereler). v2 faktör sonuçları görüldükten sonra
kurulduğu için kısmen örneklem içi; ikinci yarıdaki üstünlüğü küçük. İşlemi duran fonlar ileri fiyatı olmadığı
için testten düştü (TP2/TLY gibi kayıplar ölçülmedi). Akademik bulgularla uyumlu: getiri sürekliliği kısa vadeli
(Bollen & Busse 2005), ücretler en tutarlı öngörücü (Morningstar), akışlar geçmiş getiriyi kovalıyor (Frazzini & Lamont 2008),
düşük maksimum düşüş daha iyi sonraki getiriyle ilişkili (Riley & Yan 2022), pürüzsüz getiri illikiditeye işaret ediyor
(Getmansky, Lo & Makarov 2004). `scores` tablosu her gün birikiyor; birkaç ay sonra v2 gerçek ileri test ile yeniden doğrulanmalı.

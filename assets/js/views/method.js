import { num, dateTR, COMPONENT_LABELS, RETURN_LABELS } from "../util.js";

export function render(app, _route, store) {
  const c = store.meta.config;
  const w = c.weights;
  const pw = c.performanceWindows;
  const maxW = Math.max(...Object.values(w));

  app.innerHTML = `
  <section class="method-intro card">
    <h2>TEFAS Quant nasıl puanlıyor? <span class="model-tag">Model ${c.model || "v1"}</span></h2>
    <p>Her işlem günü TEFAS fiyatları yayımlandıktan sonra son <b>${c.historyYears} yıllık</b> veriyle
      (${dateTR(store.meta.firstDataDate)} – ${dateTR(store.meta.lastDataDate)}) tüm yatırım fonları yeniden puanlanır.
      Fonlar yalnızca <b>kendi kategorisindeki</b> fonlarla kıyaslanır; bir para piyasası fonu hisse fonuyla yarışmaz.</p>
    <ol class="steps">
      <li><b>Evren:</b> Sıralamaya alınmayanlar: halka açık olmayan <b>özel fonlar</b>; son ${c.stalePriceDays} günde fiyatı yayımlanmayanlar;
        işlemleri durdurulup son 3 ayda %50'den fazla değer kaybeden ya da büyüklüğü %90'dan fazla eriyenler; pay adedi ve yatırımcı sayısı
        10 işlem günüdür hiç değişmeyenler (alım-satım fiilen durmuş); 60 işlem gününden kısa geçmişi olanlar.
        Pay bölünmeleri (ör. İş Portföy TI2, fiyat 10.000'e bölündü) geçmiş fiyatlar oranlanarak düzeltilir.</li>
      <li><b>Beş bileşen</b> 0–100 arası puanlanır ve ağırlıklandırılır.</li>
      <li><b>Cezalar ve ayarlar</b> uygulanır.</li>
      <li><b>Not:</b> kategori içi sıraya göre verilir: üst %32,5 A (Al), sonraki %35 B (İzle), %22,5 C (Zayıf), alt %10 D (Uzak Dur).
        <b>A+ (Güçlü Al)</b> yalnızca şu şartların hepsini sağlayan fonlara verilir: kategorisinde en üst %${100 - (c.strongBuy?.top_percentile ?? 95)},
        en az 1 yıllık geçmiş, en az ${num(c.strongBuy?.min_investors ?? 1000, 0)} yatırımcı, en az ${num((c.strongBuy?.min_aum ?? 1e8) / 1e6, 0)} mn ₺ büyüklük,
        getiri anomalisi cezası yok, önceki ${c.strongBuy?.streak_months ?? 2} ay sonunda da A veya A+, kurucu riski yok,
        kuyruk riski kategorinin en kötü %10'unda değil ve son 1 ayda büyüklüğün %${c.riskFlags?.hot_money_flow_pct ?? 30}'undan fazla net giriş (sıcak para) yok.</li>
    </ol>
  </section>

  <div class="grid grid-2">
    <section class="card">
      <div class="card-head"><h2>Bileşen ağırlıkları</h2></div>
      <div class="weights">${Object.entries(w).map(([k, v]) => `
        <div class="weight-row"><span>${COMPONENT_LABELS[k]}</span><span class="scorebar"><i style="width:${(v / maxW) * 100}%"></i></span><b>%${num(v * 100, 0)}</b></div>`).join("")}
      </div>
      <dl class="defs">
        <dt>Performans</dt><dd>${Object.entries(pw).map(([k, x]) => `${RETURN_LABELS[k]} %${num(x.weight * 100, 0)}`).join(" · ")} —
          her dönemin getirisi kategori içi yüzdeliğe çevrilir. Pencereler işlem günüdür (1 yıl = 252 gün).</dd>
        <dt>Risk <span class="dim">(son ${c.riskWindowDays} işlem günü)</span></dt><dd>Sharpe %40, maksimum düşüş %30, Sortino %20, pürüzsüzlük %10.
          Sharpe/Sortino risksiz faize göre hesaplanır: para piyasası fonlarının günlük medyan getirisi (bugün yıllık %${num(store.meta.riskFree, 1)}).
          Pürüzsüzlük, günlük getirilerin otokorelasyonudur; fiyatı olağan dışı düzgün ilerleyen fonlar (değerlemesi zor ya da likit olmayan varlıklar) puan kaybeder.</dd>
        <dt>Maliyet</dt><dd>Yönetim ücreti, kategori içinde: en ucuz fon ~100, en pahalı ~0. Stopaj kategoriye göre neredeyse sabit olduğu için ayrım yapmaz; skora girmez, fon sayfasında gösterilir.</dd>
        <dt>Yatırımcı & akış</dt><dd>1 aylık büyüklük değişimi %50, 3 aylık net akış / büyüklük %50. Akışlar geçmiş getiriyi kovaladığı için düşük ağırlıklıdır; büyük çıkışlar ayrıca cezalandırılır.</dd>
        <dt>Portföy kalitesi</dt><dd>Kategori içinde fon büyüklüğü.</dd>
      </dl>
      <div class="notice"><b>Neden bu ağırlıklar?</b> v2, 3 yıllık TEFAS verisinde geriye dönük ama o günün verisiyle (point-in-time) test edildi:
        Ekim 2024 – Temmuz 2026 arasında her ay fonlar kategori içinde sıralandı ve sonraki 3 ayın getirisiyle karşılaştırıldı (T+2 giriş).
        Önceki modelin sıra korelasyonu (rank IC) 0,243 iken v2'ninki 0,273. En güçlü öngörücüler 6 aylık ve 1 yıllık getiri ile Sharpe oranıydı;
        yatırımcı sayısı ve akışın öngörü gücü sıfıra yakındı. Geçmiş performans geleceği garanti etmez.</div>
    </section>

    <section class="card">
      <div class="card-head"><h2>Cezalar ve ayarlar</h2></div>
      <table class="kv rules">
        <tr><th colspan="2">Az yatırımcı cezası</th></tr>
        ${c.investorPenalties.map(([lim, p]) => `<tr><td>&lt; ${num(lim, 0)} yatırımcı</td><td class="down">−${p}</td></tr>`).join("")}
        <tr><th colspan="2">Net nakit çıkışı cezası <span class="dim">(akış / büyüklük, puanın yarısı düşülür)</span></th></tr>
        ${c.outflowPenalties.map(([lim, p]) => `<tr><td>&lt; %${lim}</td><td class="down">−${num(p / 2, 1)}</td></tr>`).join("")}
        <tr><th colspan="2">Getiri anomalisi cezası</th></tr>
        <tr><td>1Y getirinin kategori içi robust z-skoru (medyan / IQR) ${num(c.anomaly.z, 0)}'ü aştığında her birim için</td><td class="down">−${num(c.anomaly.perZ, 0)}</td></tr>
        <tr><td>Üst sınır</td><td class="down">−${num(c.anomaly.max, 0)}</td></tr>
        <tr><th colspan="2">Kurucu riski</th></tr>
        <tr><td>Portföy şirketinin halka açık fonlarının en az %${num((c.founderRisk?.min_share ?? 0.3) * 100, 0)}'u (en az ${c.founderRisk?.min_funds ?? 3}) işleme kapalı, çökmüş ya da fiyatı durmuşsa kalan fonlarına; not en fazla İZLE</td><td class="down">−${num(c.founderRisk?.penalty ?? 10, 0)}</td></tr>
        <tr><th colspan="2">Sert düşüş cezası</th></tr>
        <tr><td>Son 3 ayda tepeden düşüş, kategori medyanından ${num(c.riskFlags?.drawdown_rel_points ?? 10, 0)} puandan fazlaysa</td><td class="down">−${num(c.riskFlags?.drawdown_penalty ?? 3, 0)}</td></tr>
        <tr><th colspan="2">Bilgi notu (ceza yok)</th></tr>
        <tr><td>Yoğunlaşma: 1 ayda yatırımcı sayısı azalırken (&lt; %${c.riskFlags?.concentration_investor_pct ?? -2}) büyüklüğün %${c.riskFlags?.concentration_flow_pct ?? 5}'inden fazla net giriş</td><td class="dim">not</td></tr>
        <tr><th colspan="2">Ayarlar</th></tr>
        <tr><td>Veri güveni (geçmiş uzunluğu, süreklilik, güncellik)</td><td>−5 … +5</td></tr>
        <tr><td>Yatırımcı istikrarı (yatırımcı sayısı kademesi)</td><td>−5 … +3</td></tr>
      </table>
      <div class="notice">
        <b>Neden anomali cezası?</b> Eylül 2026'da işlemleri durdurulan Tera Portföy fonları (TP2, TLY…) pürüzsüz ve
        kategorisinin çok üstünde getiri yazdığı için risk metriklerinde kusursuz görünüyordu. Fiyat verisi kredi ve likidite riskini
        göremez; olağan dışı getiri bu yüzden ödül değil uyarı sayılır.
      </div>
    </section>
  </div>

  <section class="card">
    <div class="card-head"><h2>Veri ve güncelleme</h2></div>
    <ul class="plain">
      <li>Kaynak: TEFAS'ın herkese açık fon verisi (fiyat, pay adedi, yatırımcı sayısı, portföy büyüklüğü) ve resmî şemsiye fon türleri.
        Yönetim ücreti, stopaj ve işlem durumu haftada bir FVT'den alınır.</li>
      <li>Güncelleme: her işlem günü, TEFAS günün fiyatlarını yayımladıktan sonra <b>günde bir kez</b>. Gün içi veri yoktur.</li>
      <li>Saklanan geçmiş: son ${c.historyYears} yıl. Daha eski kayıtlar her güncellemede silinir.</li>
      <li>Sınırlar: Sıralama geçmiş fiyatlara dayanır; kredi, likidite ve operasyonel riskleri tam yansıtmaz.
        Yatırım tavsiyesi değildir.</li>
    </ul>
  </section>`;
}

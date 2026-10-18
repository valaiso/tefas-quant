import { num, dateTR, COMPONENT_LABELS, RETURN_LABELS } from "../util.js";

export function render(app, _route, store) {
  const c = store.meta.config;
  const w = c.weights;
  const pw = c.performanceWindows;

  app.innerHTML = `
  <section class="method-intro card">
    <h2>TEFAS Quant nasıl puanlıyor?</h2>
    <p>Her işlem günü TEFAS fiyatları yayımlandıktan sonra son <b>${c.historyYears} yıllık</b> veriyle
      (${dateTR(store.meta.firstDataDate)} – ${dateTR(store.meta.lastDataDate)}) tüm yatırım fonları yeniden puanlanır.
      Fonlar yalnızca <b>kendi kategorisindeki</b> fonlarla kıyaslanır; bir para piyasası fonu hisse fonuyla yarışmaz.</p>
    <ol class="steps">
      <li><b>Evren:</b> Son ${c.stalePriceDays} günde fiyatı yayımlanmayan (askıya alınmış, tasfiyedeki, kapanmış) fonlar ve
        60 işlem gününden kısa geçmişi olanlar dışarıda kalır.</li>
      <li><b>Beş bileşen</b> 0–100 arası puanlanır ve ağırlıklandırılır.</li>
      <li><b>Cezalar ve ayarlar</b> uygulanır.</li>
      <li><b>Not:</b> ${c.ratingMode === "relative"
        ? "kategori içi sıraya göre verilir: üst %10 A+ (Güçlü Al), sonraki %22,5 A (Al), %35 B (İzle), %22,5 C (Zayıf), alt %10 D (Uzak Dur)."
        : "sabit skor eşikleriyle verilir (85 / 75 / 65 / 55)."}</li>
    </ol>
  </section>

  <div class="grid grid-2">
    <section class="card">
      <div class="card-head"><h2>Bileşen ağırlıkları</h2></div>
      <div class="weights">${Object.entries(w).map(([k, v]) => `
        <div class="weight-row"><span>${COMPONENT_LABELS[k]}</span><span class="scorebar"><i style="width:${v * 100 / 0.35}%"></i></span><b>%${num(v * 100, 0)}</b></div>`).join("")}
      </div>
      <dl class="defs">
        <dt>Performans</dt><dd>${Object.entries(pw).map(([k, x]) => `${RETURN_LABELS[k]} %${num(x.weight * 100, 0)}`).join(" · ")} —
          her dönemin getirisi kategori içi yüzdeliğe çevrilir. Pencereler işlem günüdür (1 yıl = 252 gün).</dd>
        <dt>Risk</dt><dd>Volatilite %25, maksimum düşüş %25, Sharpe %20, Sortino %15, Calmar %10, beta %5.
          Sharpe/Sortino risksiz faize göre hesaplanır: para piyasası fonlarının günlük medyan getirisi (bugün yıllık %${num(store.meta.riskFree, 1)}).</dd>
        <dt>Yatırımcı & akış</dt><dd>Yatırımcı tabanı %55, 1 aylık yatırımcı değişimi %15, net akış/büyüklük %30.
          Net akış TEFAS pay adedi değişimi × fiyattan hesaplanır (3A %60, 1A %30, 1H %10).</dd>
        <dt>Maliyet</dt><dd>Yönetim ücreti kategori içinde; en pahalı fon bile 50 puanın altına düşmez.</dd>
        <dt>Portföy kalitesi</dt><dd>Büyüklük kademesi ve kategori benchmark'ına göre alfa.</dd>
      </dl>
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

import { esc, num, pct, dateTR, codeChip, gradeBadge } from "../util.js";
import { lineChart } from "../chart.js";
import { startIndex, windowed, windowStats, statRow } from "./simulation.js";

const COLORS = { model: "var(--brand-3)", ppf: "var(--c6)", gold: "var(--c7, #ca8a04)", tufe: "var(--c2)", usd: "var(--c4)" };
const LABELS = { ppf: "PPF ortalaması", gold: "Gram altın", tufe: "TÜFE", usd: "Dolar/TL" };
const SLICE = ["#0f766e", "#2563eb", "#ca8a04", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#ea580c", "#475569", "#9333ea"];
const PERIODS = [["6a", "6A", 6], ["1y", "1Y", 12], ["all", "Tümü", null]];
const ORDER = ["guvenli", "dengeli", "atak"];
const TONE = { guvenli: "safe", dengeli: "mid", atak: "risk" };
const BLURB = {
  guvenli: "Para piyasası ve kısa vadeli borçlanma ağırlıklı; sepetin en az %60'ı köklü kurucuların (devlet / büyük özel banka) fonlarında. Amaç PPF'ye yakın getiriyi en düşük dalgalanma ve yönetici riskiyle almak.",
  dengeli: "Sepetin %40'ı Güvenli sepetin fonları (çapa), kalanı orta oynaklıklı, son 3 yılda vergi sonrası enflasyonu yenmiş fonlar.",
  atak: "Hisse, altın, teknoloji gibi oynak fonlar; sıçramaya dayalı ve aşırı yükselmiş fonlar alınmaz. Kısa vadede değer kaybı yaşanabilir.",
};
const BEAT = {
  ppf_all: "1Y, 2Y ve 3Y'nin hepsinde PPF'yi geçmiş",
  ppf_near: "1Y, 2Y ve 3Y'nin hepsinde PPF'ye yakın (en fazla 2 puan altında)",
  ppf_3y: "3Y'de PPF'yi, 1Y ve 2Y'de TÜFE'yi geçmiş",
  tufe_all: "1Y, 2Y ve 3Y'nin hepsinde TÜFE'yi geçmiş (reel getiri pozitif)",
};
const state = { profile: "guvenli", period: "all", month: {} };
let cache = null;

async function load() {
  if (!cache) {
    const r = await fetch(`data/model.json?v=${Date.now().toString(36).slice(0, -3)}`);
    if (!r.ok) throw new Error(`model.json: ${r.status}`);
    cache = await r.json();
  }
  return cache;
}

const nameOf = (store, b) => store.byCode.get(b.c)?.n || b.n;

function overviewCards(m) {
  return ORDER.filter((k) => m.profiles[k]).map((k) => {
    const p = m.profiles[k];
    const st = p.backtest.available ? p.backtest.stats.model : null;
    return `<button class="profile-card tone-${TONE[k]}" data-p="${k}" aria-pressed="${k === state.profile}">
      <span class="pc-label">${esc(p.label)}</span>
      <span class="pc-main">${st ? pct(st.total, 1) : "—"}</span>
      <span class="pc-sub">geçmiş test · en büyük düşüş ${st ? pct(st.mdd, 1) : "—"}</span>
      <span class="pc-sub">${p.basket.length} fon · dönem başından ${pct(p.sinceEntry, 2)}</span>
    </button>`;
  }).join("");
}

export async function render(app, _route, store) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Model yükleniyor…</p></div>`;
  const m = await load();
  const R = m.rules;
  if (!m.profiles[state.profile]) state.profile = ORDER.find((k) => m.profiles[k]);

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Model Portföyler <span class="model-tag">2 aylık dönem</span></h2>
    <p>Üç risk profilinde, son <b>1-2-3 yılda vergi sonrası istikrarlı</b> getiri vermiş, TEFAS Quant notu ve risk bayrakları temiz,
      getirisi tek bir sıçramaya dayanmayan ${R.minFunds}–${R.maxFunds} fonluk ağırlıklı sepetler. Sepetler <b>2 ayda bir</b>
      (çift ayların son işlem günü) kurulur ve dönem boyunca sabit kalır; iyi kalan fonlar yeni dönemde de sepette kalabilir, ağırlıklar yeniden hesaplanır.
      Köklü kurucuların (devlet bankaları ve büyük özel bankaların portföy şirketleri) fonlarına öncelik verilir.</p>
    <p class="dim">Son kurulum: ${dateTR(m.profiles[state.profile].formed)} · Sonraki yenileme: <b>${dateTR(m.nextRebalance)}</b> · Veri: ${dateTR(m.asOf)}</p>
  </section>

  <div class="profile-cards" id="mdlProfiles">${overviewCards(m)}</div>
  <div id="mdlBody"></div>

  <section class="card">
    <div class="card-head"><h2>Tüm profiller için ortak kurallar</h2></div>
    <ol class="rule-list">
      <li><b>Aday havuzu:</b> halka açık (nitelikli/özel değil), en az 3 yıl geçmiş, ≥${num(R.minAum / 1e6, 0)}m TL büyüklük, ≥${num(R.minInvestors, 0)} yatırımcı,
        fiyatı güncel; kurulum günündeki TEFAS Quant notu ${R.okGrades.join(" / ")} (C ve D alınmaz) ve o gün getiri anomalisi, kuyruk riski,
        sıcak para ya da kurucu riski bayrağı yok.</li>
      <li><b>Vergi:</b> getiriler stopaj sonrası karşılaştırılır (hisse yoğun fonlarda %0, çoğu fonda %17,5; PPF kıyası %${num(R.ppfStopaj * 100, 1)} stopajla).
        Yönetim ücreti fon fiyatına zaten yansır; ayrıca düşük ücret puanda küçük avantaj sağlar.</li>
      <li><b>Sıçrama filtresi:</b> 2 yıllık getirinin %${num(R.spikeShare * 100, 0)}'ından fazlası tek aydan geliyorsa, son 3 ay kendi geçmişine göre aşırıysa
        (z &gt; ${num(R.spikeZ, 1)}), son 1 yılda tek günde ±%${num(R.spikeDay * 100, 0)}'ten büyük hareket varsa ya da 1 yıllık getiri profil sınırını aşıyorsa fon alınmaz.</li>
      <li><b>Puan:</b> vergi sonrası getiri (1Y/2Y/3Y), istikrar (12 aylık dönemlerde PPF'yi geçme oranı), Sharpe (2 yıl), azami düşüş, TEFAS Quant skoru,
        yatırımcı sayısı ve yönetim ücreti; profil ağırlıkları aşağıda. Köklü kurucuya +${num(R.bankBonus, 0)}, önceki dönem sepette olan fona
        +${num(R.stayBonus, 0)} süreklilik puanı.</li>
      <li><b>Çeşitlendirme:</b> aynı portföy şirketinden tek fon; kategori başına sınır; seçilmiş bir fonla haftalık getiri korelasyonu &gt; ${num(R.maxCorr, 2)}
        olan fon alınmaz (Güvenli hariç: düşük oynaklıklı fonlar faizle birlikte hareket eder).</li>
      <li><b>Yönetici riski:</b> Güvenli sepetin en az %60'ı, Dengeli ve Atak'ın kendi fonlarının en az %50'si köklü kurucularda; diğer kurucuların tek fonu
        Güvenli ve Atak'ta en fazla %20, Dengeli'de %15. <span class="dim">Neden: Ekim 2026'da Pardus Portföy'ün para piyasası fonu dahil fonları
        tek seferde ~%99 değer kaybetti; kuruluş günü fon temiz görünüyordu.</span></li>
      ${R.excludedFounders?.length ? `<li><b>Hariç tutulan kurucular:</b> ${R.excludedFounders.map((x) => `<b>${esc(x.name)}</b> (${x.funds} fon): ${esc(x.why)}`).join("; ")}.
        Bu kurucuların hiçbir fonu, notu ne olursa olsun hiçbir profile alınmaz.</li>` : ""}
      <li><b>Ağırlık:</b> puan² / oynaklık ile orantılı; her fon %${num(R.minW * 100, 0)}–%${num(R.maxW * 100, 0)}, 5'in katlarına yuvarlanır.</li>
      <li><b>Köklü kurucular:</b> <span class="dim">${R.banks.map(esc).join(", ")}</span></li>
    </ol>
  </section>`;

  const drawProfile = () => {
    const key = state.profile;
    const p = m.profiles[key];
    const basket = p.basket;
    const bt = p.backtest;
    const months = p.history.map((h) => h.date);
    if (!state.month[key] || !months.includes(state.month[key])) state.month[key] = months[months.length - 1];

    const bar = basket.map((b, i) => `<span style="width:${b.w}%;background:${SLICE[i % SLICE.length]}" title="${esc(b.c)} %${b.w}">${esc(b.c)} %${b.w}</span>`).join("");
    const warnN = basket.filter((b) => b.warn).length;
    const rows = basket.map((b, i) => `<tr>
        <td class="left"><span class="mdl-swatch" style="background:${SLICE[i % SLICE.length]}"></span>${codeChip(b.c)}
          ${b.bank ? `<span class="bank-tag" title="${esc(b.fd || "")}: köklü kurucu (devlet / büyük özel banka)">KÖKLÜ</span>` : ""}
          ${b.cash ? `<span class="leg-tag" title="Güvenli sepetten gelen çapa fonu">ÇAPA</span>` : ""}
          <span class="fund-name">${esc(nameOf(store, b))}</span></td>
        <td class="left dim">${esc(b.k || "—")}</td>
        <td><b class="weight">%${b.w}</b></td>
        <td>${num(b.score, 0)}</td>
        <td>${store.byCode.has(b.c) ? gradeBadge(store.byCode.get(b.c)) : (b.g ? esc(b.g) : "—")}</td>
        <td>${pct(b.net["1y"], 1)}</td><td>${pct(b.net["2y"], 1)}</td><td>${pct(b.net["3y"], 1)}</td>
        <td>%${num(b.st, 1)}</td>
        <td>${b.inv != null ? num(b.inv, 0) : "—"}</td>
        <td>%${num(b.win, 0)}</td>
        <td class="down">${pct(b.mdd, 1)}</td>
        <td>%${num(b.vol, 1)}</td>
        <td class="left">${b.warn ? `<span class="warn-tag">${esc(b.warn)}</span>` : `<span class="dim">—</span>`}</td>
      </tr>`).join("");
    const ru = p.rules;
    const W = ru.weights;

    app.querySelector("#mdlBody").innerHTML = `
    <section class="card">
      <div class="card-head"><h2>${esc(p.label)} sepet</h2>
        <span class="sub">${dateTR(p.formed)} kuruldu · ${dateTR(p.entry)} alış · sonraki yenileme ${dateTR(m.nextRebalance)}</span></div>
      <p class="dim">${esc(BLURB[key])}</p>
      <div class="kpi-row">
        <div><span>Dönem başından bugüne</span><b class="${(p.sinceEntry ?? 0) >= 0 ? "up" : "down"}">${pct(p.sinceEntry, 2)}</b></div>
        <div><span>3Y yıllık (vergi sonrası)</span><b>${pct(p.portfolio.net_3y, 1)}</b></div>
        <div><span>PPF 3Y yıllık (vergi sonrası)</span><b>${pct(p.bench["3y"]?.ppfNet, 1)}</b></div>
        <div><span>Ağırlıklı oynaklık</span><b>%${num(p.portfolio.vol, 1)}</b></div>
        <div><span>Havuz</span><b>${p.pool} fon</b></div>
      </div>
      <div class="weight-bar">${bar}</div>
      <div class="table-wrap"><table class="model-table">
        <thead><tr><th class="left">Fon</th><th class="left">Kategori</th><th>Ağırlık</th><th title="Profil puanı (0-100)">Puan</th><th>Not</th>
          <th title="Vergi (stopaj) sonrası yıllık">1Y net</th><th title="Vergi sonrası yıllık bileşik">2Y net</th><th title="Vergi sonrası yıllık bileşik">3Y net</th>
          <th>Stopaj</th><th>Yatırımcı</th><th title="Son 2 yılda 12 aylık dönemlerin kaçında PPF'yi geçti">PPF'yi geçen 12A</th>
          <th>Maks. düşüş (2Y)</th><th>Oynaklık (1Y)</th><th class="left">Bugünkü durum</th></tr></thead>
        <tbody>${rows}</tbody>
        <tfoot>
          <tr class="is-self"><td class="left"><b>Sepet (ağırlıklı)</b></td><td></td><td><b>%100</b></td><td></td><td></td>
            <td><b>${pct(p.portfolio.net_1y, 1)}</b></td><td><b>${pct(p.portfolio.net_2y, 1)}</b></td><td><b>${pct(p.portfolio.net_3y, 1)}</b></td><td colspan="6"></td></tr>
          <tr><td class="left dim">PPF ortalaması (vergi sonrası)</td><td></td><td></td><td></td><td></td>
            <td>${pct(p.bench["1y"]?.ppfNet, 1)}</td><td>${pct(p.bench["2y"]?.ppfNet, 1)}</td><td>${pct(p.bench["3y"]?.ppfNet, 1)}</td><td colspan="6"></td></tr>
          <tr><td class="left dim">TÜFE</td><td></td><td></td><td></td><td></td>
            <td>${pct(p.bench["1y"]?.tufe, 1)}</td><td>${pct(p.bench["2y"]?.tufe, 1)}</td><td>${pct(p.bench["3y"]?.tufe, 1)}</td><td colspan="6"></td></tr>
        </tfoot>
      </table></div>
      ${warnN ? `<div class="notice warn"><b>${warnN} fonda dönem içinde uyarı var.</b> Sepet 2 aylık dönem boyunca sabit kalır; uyarılar bir sonraki
        kurulumda (${dateTR(m.nextRebalance)}) değerlendirilir ve bayraklı fon o zaman sepete alınmaz.</div>` : ""}
      <div class="notice warn">Bu sayfa bir <b>model çıktısıdır, yatırım tavsiyesi değildir</b>. Geçmiş getiri gelecek getirinin göstergesi değildir;
        kişisel risk tercihin, vaden ve vergi durumun dikkate alınmadı. Fon alım-satım valörleri ve giriş/çıkış kuralları hesaba katılmadı.</div>
    </section>

    ${bt.available ? `<section class="card">
      <div class="card-head"><h2>${esc(p.label)} model geçmişte nasıl sonuç verdi?</h2>
        <div class="seg" id="mdlPeriod">${PERIODS.map(([k, l]) => `<button data-p="${k}" aria-pressed="${k === state.period}">${l}</button>`).join("")}</div>
      </div>
      <div class="chart" id="mdlChart"></div>
      <p class="chart-note dim" id="mdlRange"></p>
      <div class="table-wrap"><table id="mdlStats"></table></div>
      <div class="notice">Her dönem başında sepet <b>yalnızca o gün bilinen verilerle</b> (o günkü not, bayraklar, fiyatlar) aynı kurallarla yeniden kuruldu,
        ertesi işlem günü (T+1) alındı ve 2 ay tutuldu. Getiriler stopaj öncesidir (kıyaslarla aynı). "En kötü / en iyi ay" sütunu 2 aylık dönemleri gösterir.
        Model 3 yıllık geçmiş istediği için ${dateTR(bt.dates[0])} tarihinde başlıyor; ${p.history.length} dönemlik kısa bir test, sonuçlar dikkatle okunmalı.</div>
    </section>` : ""}

    ${months.length ? `<section class="card">
      <div class="card-head"><h2>Geçmiş dönem sepetleri</h2>
        <select id="mdlMonth">${months.slice().reverse().map((d) => `<option value="${d}" ${d === state.month[key] ? "selected" : ""}>${dateTR(d)}</option>`).join("")}</select>
      </div>
      <div id="mdlHoldings"></div>
    </section>` : ""}

    ${p.spiky.length ? `<section class="card">
      <div class="card-head"><h2>Sıçrama ya da aşırı yükseliş nedeniyle alınmayanlar</h2><span class="sub">Bu profilin oynaklık sınırındaki fonlar</span></div>
      <div class="table-wrap"><table class="compact">
        <thead><tr><th class="left">Fon</th><th class="left">Kategori</th><th>1Y</th><th class="left">Neden</th></tr></thead>
        <tbody>${p.spiky.map((s) => `<tr><td class="left">${store.byCode.has(s.c) ? codeChip(s.c) : esc(s.c)} <span class="fund-name">${esc(s.n)}</span></td>
          <td class="left dim">${esc(s.k || "—")}</td><td>${pct(s.r1, 1)}</td><td class="left">${esc(s.why)}</td></tr>`).join("")}</tbody>
      </table></div>
    </section>` : ""}

    <section class="card">
      <div class="card-head"><h2>${esc(p.label)} profil kuralları</h2></div>
      <ul class="rule-list">
        <li><b>Oynaklık (1Y):</b> %${num(ru.vol[0] * 100, 0)} – %${num(ru.vol[1] * 100, 0)} · <b>Azami düşüş (2Y):</b> en fazla ${pct(ru.mdd * 100, 0)}
          · <b>1Y getiri tavanı:</b> %${num(ru.max1y * 100, 0)}</li>
        <li><b>Kıyas şartı (vergi sonrası):</b> ${esc(BEAT[ru.beat] || ru.beat)}${ru.win ? `; 12 aylık dönemlerin en az %${num(ru.win * 100, 0)}'ında PPF'yi geçmiş` : ""}.</li>
        <li><b>Puan ağırlıkları:</b> getiri ${W.ret}, istikrar ${W.win}, Sharpe ${W.sharpe}, düşüş ${W.mdd}, TEFAS Quant skoru ${W.quant}, yatırımcı ${W.inv}, ücret ${W.fee}.</li>
        <li><b>Kategori sınırı:</b> aynı kategoriden en fazla ${ru.perCat} fon.</li>
      </ul>
    </section>`;

    if (bt.available) {
      const keys = Object.keys(bt.series);
      const periodMonths = () => PERIODS.find(([k]) => k === state.period)[2];
      const draw = () => {
        const i0 = startIndex(bt.dates, periodMonths());
        const d = bt.dates.slice(i0);
        lineChart(app.querySelector("#mdlChart"), keys.map((k) => ({ name: k === "model" ? `${p.label} model` : LABELS[k] || k, d, v: windowed(bt.series[k], i0), color: COLORS[k] })),
          { base: 100, height: 300, format: (v) => num(v, 0) });
        app.querySelector("#mdlRange").textContent = `${dateTR(d[0])} – ${dateTR(d[d.length - 1])} · dönem başı = 100 · 2 ayda bir yeniden kurulum`;
        const ppfW = bt.series.ppf ? windowed(bt.series.ppf, i0) : null;
        app.querySelector("#mdlStats").innerHTML = `
          <thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th>
            <th>En kötü / en iyi dönem</th><th>Pozitif dönem</th><th>PPF'yi geçen dönem</th></tr></thead>
          <tbody>${keys.map((k, i) => statRow(k === "model" ? `${p.label} model` : LABELS[k] || k, windowStats(d, windowed(bt.series[k], i0), k === "ppf" ? null : ppfW), i === 0 ? "is-self" : "")).join("")}</tbody>`;
      };
      app.querySelector("#mdlPeriod").addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        state.period = b.dataset.p;
        app.querySelectorAll("#mdlPeriod button").forEach((x) => x.setAttribute("aria-pressed", x === b));
        draw();
      });
      draw();
    }

    if (months.length) {
      const drawHoldings = () => {
        const h = p.history.find((x) => x.date === state.month[key]);
        app.querySelector("#mdlHoldings").innerHTML = `<p class="dim">${dateTR(h.date)} sonunda kurulan ${h.items.length} fonluk sepet (havuz: ${h.pool} fon).</p>
          <div class="chip-cloud">${h.items.map(([c, w]) => `<span class="hold-chip">${store.byCode.has(c) ? codeChip(c) : `<span class="code-chip muted-chip" title="Bugün derecelendirilmiyor">${esc(c)}</span>`}<b>%${w}</b></span>`).join("")}</div>`;
      };
      app.querySelector("#mdlMonth").addEventListener("change", (e) => { state.month[key] = e.target.value; drawHoldings(); });
      drawHoldings();
    }
  };

  app.querySelector("#mdlProfiles").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-p]");
    if (!b) return;
    state.profile = b.dataset.p;
    app.querySelectorAll("#mdlProfiles button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    drawProfile();
  });
  drawProfile();
}

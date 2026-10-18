import { esc, num, pct, pctCell, money, dateTR, gradeBadge, codeChip, scoreBar, SIGNALS } from "../util.js";
import { qualifiedToggle, includeQualified, bindQualified, bindRows } from "./common.js";

export function render(app, _route, store) {
  const { meta } = store;
  const funds = store.funds.filter((f) => includeQualified() || !f.q);
  const counts = Object.fromEntries(SIGNALS.map((s) => [s.key, funds.filter((f) => f.sig === s.key).length]));
  const total = funds.length || 1;

  // Kategori liderleri: kategori içi 1. sıradaki fon (en az 5 fonluk kategoriler)
  const byCat = new Map();
  for (const f of funds) {
    if (f.ct < 5) continue;
    const cur = byCat.get(f.k);
    if (!cur || f.s > cur.s) byCat.set(f.k, f);
  }
  const leaders = [...byCat.values()].sort((a, b) => b.ct - a.ct);
  const top = [...funds].sort((a, b) => b.s - a.s).slice(0, 15);
  const anomalies = funds.filter((f) => (f.p.anomaly || 0) > 0).sort((a, b) => b.p.anomaly - a.p.anomaly);

  app.innerHTML = `
  <section class="hero">
    <div class="hero-copy">
      <span class="hero-eyebrow">GÜNLÜK DERECELENDİRME · ${dateTR(meta.lastDataDate)}</span>
      <h2>TEFAS fonları, kendi puanlama ve ceza kurallarımızla kategori içinde sıralandı.</h2>
      <p>Performans, risk, yatırımcı akışı, maliyet ve portföy kalitesi tek bir 0–100 skorda birleşir.
         Az yatırımcı, nakit çıkışı ve olağan dışı getiri cezalandırılır; fiyatı durmuş fonlar listeye alınmaz.</p>
      <div class="hero-actions">
        <a class="btn btn-light" href="#/siralama">Tüm sıralama</a>
        <a class="btn btn-ghost" href="#/metodoloji">Yöntemi incele</a>
      </div>
    </div>
    <div class="hero-figures">
      <div><span>Derecelendirilen fon</span><strong>${num(funds.length, 0)}</strong></div>
      <div><span>A+ · Güçlü Al</span><strong>${num(counts["GÜÇLÜ AL"], 0)}</strong></div>
      <div><span>Risksiz faiz (1Y, PPF medyan)</span><strong>%${num(meta.riskFree, 1)}</strong></div>
      <div><span>Listeden çıkarılan</span><strong>${num(meta.excluded.length, 0)}</strong></div>
    </div>
  </section>

  <div class="toolbar">${qualifiedToggle()}</div>

  <section class="card">
    <div class="card-head"><h2>Not dağılımı</h2><span class="sub">Kategori içi göreli not: üst %10 A+, sonraki %22,5 A, %35 B, %22,5 C, alt %10 D</span></div>
    <div class="dist-bar">${SIGNALS.map((s) =>
      `<span class="${s.cls}" style="flex:${counts[s.key] || 0.0001}" title="${s.key}: ${counts[s.key]}"></span>`).join("")}</div>
    <div class="dist-legend">${SIGNALS.map((s) =>
      `<a href="#/siralama?sig=${encodeURIComponent(s.key)}" class="dist-item"><span class="grade ${s.cls}">${s.grade}</span>
        <span>${s.key}</span><b class="num">${num(counts[s.key], 0)}</b><span class="dim num">%${num((counts[s.key] / total) * 100, 0)}</span></a>`).join("")}
    </div>
  </section>

  <section>
    <div class="section-head"><h2>Kategori liderleri</h2><span class="sub">Her kategoride en yüksek skorlu fon</span></div>
    <div class="grid grid-leaders">${leaders.map((f) => `
      <a class="card leader" href="#/fon/${encodeURIComponent(f.c)}">
        <div class="leader-top"><span class="leader-cat">${esc(f.k)}</span>${gradeBadge(f)}</div>
        <div class="leader-code">${esc(f.c)}</div>
        <div class="leader-name">${esc(f.n)}</div>
        <div class="leader-figs">
          <div><span>Skor</span><b>${num(f.s, 1)}</b></div>
          <div><span>1 Yıl</span><b class="${f.r["1y"] >= 0 ? "up" : "down"}">${pct(f.r["1y"], 1)}</b></div>
          <div><span>Fon sayısı</span><b>${f.ct}</b></div>
        </div>
      </a>`).join("")}
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Genel ilk 15</h2><a class="btn btn-sm" href="#/siralama">Tümünü gör →</a></div>
    <div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Fon</th><th class="left">Kategori</th><th>Not</th><th>Skor</th><th>1 Ay</th><th>1 Yıl</th><th>Volatilite</th><th>Büyüklük</th></tr></thead>
      <tbody>${top.map((f, i) => `
        <tr class="row-link" data-href="#/fon/${encodeURIComponent(f.c)}">
          <td class="dim">${i + 1}</td>
          <td class="fund-cell">${codeChip(f.c)}<span class="name">${esc(f.n)}</span></td>
          <td class="left dim">${esc(f.k)}</td>
          <td>${gradeBadge(f)}</td>
          <td class="score-cell">${scoreBar(f.s)}</td>
          <td>${pctCell(f.r["1a"])}</td>
          <td>${pctCell(f.r["1y"])}</td>
          <td>%${num(f.m.vol, 1)}</td>
          <td>${money(f.aum)}</td>
        </tr>`).join("")}
      </tbody></table></div>
  </section>

  <div class="grid grid-2">
    <section class="card">
      <div class="card-head"><h2>Listeden çıkarılan fonlar</h2><span class="sub">${num(meta.excluded.length, 0)} fon · işleme kapalı, fiyatı duran ya da alım-satımı donmuş</span></div>
      ${meta.excluded.length ? `<div class="table-wrap"><table class="compact excluded">
        <thead><tr><th>Fon</th><th>Son fiyat</th><th class="left">Neden</th></tr></thead>
        <tbody>${meta.excluded.map((x, i) => `<tr ${i >= 12 ? 'class="more" hidden' : ""}><td class="fund-cell"><b class="mono">${esc(x.code)}</b><span class="name">${esc(x.name)}</span></td>
          <td>${dateTR(x.lastDate)}</td><td class="left"><span class="pill down">${esc(x.reason)}</span></td></tr>`).join("")}</tbody>
      </table></div>
      ${meta.excluded.length > 12 ? `<button class="btn btn-sm show-more" type="button">Tümünü göster (${meta.excluded.length})</button>` : ""}
      ${meta.privateSkipped ? `<p class="dim small">Ayrıca halka açık olmayan ${num(meta.privateSkipped, 0)} özel fon sıralamaya alınmaz.</p>` : ""}` : `<p class="dim">Fiyatı duran fon yok.</p>`}
    </section>
    <section class="card">
      <div class="card-head"><h2>Getiri anomalisi cezası alanlar</h2><span class="sub">1Y getirisi kategorisinin çok üstünde</span></div>
      ${anomalies.length ? `<div class="table-wrap"><table class="compact">
        <thead><tr><th>Fon</th><th>1 Yıl</th><th>Ceza</th></tr></thead>
        <tbody>${anomalies.slice(0, 12).map((f) => `<tr class="row-link" data-href="#/fon/${encodeURIComponent(f.c)}">
          <td class="fund-cell">${codeChip(f.c)}<span class="name">${esc(f.n)}</span></td>
          <td>${pctCell(f.r["1y"], 1)}</td><td class="down">−${num(f.p.anomaly, 1)}</td></tr>`).join("")}</tbody>
      </table></div>` : `<p class="dim">Bu dönemde anomali cezası yok.</p>`}
    </section>
  </div>`;

  bindRows(app);
  bindQualified(app, () => render(app, _route, store));
  app.querySelector(".show-more")?.addEventListener("click", (e) => {
    app.querySelectorAll("table.excluded tr.more").forEach((tr) => (tr.hidden = false));
    e.target.remove();
  });
}

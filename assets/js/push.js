// Aylık rapor bildirimleri (Web Push): ayın 1'i ve son günü 09:00 ve 18:00'de gelir.
// Telefonda üst çubuktaki zil simgesi durumu gösterir ve dokununca açıp kapatır. iPhone bildirime yalnızca
// ana ekrana eklenmiş uygulamada ve bir dokunuşla izin verdirir. Abonelik Analiz hesabına
// (Supabase push_subscriptions, app: "tefas-quant") yazılır; gönderimi Analiz deposundaki GitHub işi yapar.
import { supabaseClient } from "./supabase.js";

const VAPID_PUBLIC_KEY = "BCqEzXeK-J1lFgWvYoOmd1SnveNzmq1L-Ch_IalHNbSeRc79o0fJ7bUAIbMn42ZAcqc0wqfOHMzW4gmN2AZ6yQQ";
const BASE = new URL("./", location.href).pathname;  // /tefas-quant/
const APP = "tefas-quant";

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const standalone = () => matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);

function keyToBytes(b64) {
  const s = `${b64}${"=".repeat((4 - (b64.length % 4)) % 4)}`.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}
const register = () => navigator.serviceWorker.register(`${BASE}sw.js`, { scope: BASE, updateViaCache: "none" });
const currentSub = async () => (await navigator.serviceWorker.getRegistration(BASE))?.pushManager.getSubscription();

async function save(sb, sub) {
  const { data: { user } } = await sb.auth.getUser();
  if (!user) throw new Error("Önce Analiz hesabınla giriş yap.");
  const { error } = await sb.from("push_subscriptions").upsert({
    user_id: user.id, endpoint: sub.endpoint, subscription: { ...sub.toJSON(), app: APP }, updated_at: new Date().toISOString(),
  }, { onConflict: "endpoint" });
  if (error) throw new Error(`Abonelik kaydedilemedi: ${error.message}`);
}

/** 'needs-home-screen' | 'unsupported' | 'denied' | 'on' | 'off' */
async function status() {
  if (isIOS() && !standalone()) return "needs-home-screen";
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return Notification.permission === "granted" && (await currentSub()) ? "on" : "off";
}

async function enable(sb, permP = null) {
  const perm = await (permP || Notification.requestPermission());
  if (perm !== "granted") throw new Error("Bildirim izni verilmedi.");
  const reg = await register();
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(VAPID_PUBLIC_KEY) }));
  await save(sb, sub);
}

// Elle kapatınca bu cihazdaki hesap oturumu da kapanır: yeniden açarken e-posta ve parola her zaman sorulur
async function disable(sb) {
  const sub = await currentSub();
  if (sub) {
    await sb.from("push_subscriptions").delete().eq("endpoint", sub.endpoint);
    await sub.unsubscribe();
  }
  await sb.auth.signOut({ scope: "local" });
}

// ------------------------------------------------------------------ arayüz
const BELL = '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>';
const icon = (on) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="${on ? "currentColor" : "none"}" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${BELL}${on ? "" : '<path d="M3 3l18 18"/>'}</svg>`;

function toast(text) {
  const t = document.createElement("div");
  t.className = "push-toast";
  t.textContent = text;
  document.body.append(t);
  setTimeout(() => t.remove(), 3200);
}

/** Kurulum adımı gerektiğinde (giriş, ana ekrana ekleme, izin) üstte kısa bir kart gösterir. */
function card(inner) {
  const box = document.getElementById("pushSetup");
  if (!box) return null;
  box.innerHTML = `<section class="card push-card"><h2>Aylık rapor bildirimleri
      <button class="icon-btn push-close" type="button" aria-label="Kapat">✕</button></h2>
    <p>Ayın 1'inde (raporlar bugün gelecek / gönderildi) ve ayın son gününde (raporlar yarın gelecek) saat 09:00 ve 18:00'de gelir.</p>${inner}</section>`;
  box.hidden = false;
  box.querySelector(".push-close").addEventListener("click", () => (box.hidden = true));
  return box;
}

export async function initPush() {
  const btn = document.getElementById("pushBtn");
  if (!btn) return;
  if (supported()) register().then((r) => r.update()).catch(() => {});
  const sbP = supabaseClient();

  const paint = async () => {
    const s = await status().catch(() => "unsupported");
    btn.innerHTML = icon(s === "on");
    btn.classList.toggle("is-on", s === "on");
    const label = s === "on" ? "Aylık rapor bildirimleri açık" : "Aylık rapor bildirimleri kapalı";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.setAttribute("aria-pressed", String(s === "on"));
    return s;
  };

  const turnOn = async (sb, permP) => {
    await enable(sb, permP);
    document.getElementById("pushSetup").hidden = true;
    const { data: { user } } = await sb.auth.getUser();
    toast(`Bildirimler açıldı (${user?.email || "hesap"}) · ayın 1'i ve son günü 09:00 ve 18:00`);
    await paint();
  };

  btn.addEventListener("click", async () => {
    // İzin penceresi dokunuşun hemen ardından açılmalı (iPhone, araya giren ağ beklemelerinde izni reddeder)
    const permP = !btn.classList.contains("is-on") && supported() && standalone() && Notification.permission === "default"
      ? Notification.requestPermission() : null;
    const s = await status().catch(() => "unsupported");
    const sb = await sbP;
    if (s === "needs-home-screen") {
      card(`<p class="dim">iPhone bildirime yalnızca ana ekran uygulamasında izin verir: Safari'de Paylaş → Ana Ekrana Ekle,
        sonra TEFAS Quant'ı ana ekrandaki simgeden aç ve zile dokun.</p>`);
      return;
    }
    if (s === "unsupported") { toast("Bu cihaz bildirimleri desteklemiyor (iPhone'da iOS 16.4 veya üstü gerekir)."); return; }
    if (s === "denied") { toast("Bildirim izni kapalı: iPhone Ayarlar → Bildirimler → TEFAS Quant."); return; }
    btn.disabled = true;
    try {
      const { data: { session } } = await sb.auth.getSession();
      if (s === "on") {
        if (!session) throw new Error("Kapatmak için Analiz hesabınla giriş yap.");
        await disable(sb);
        toast("Bildirimler kapatıldı · yeniden açarken hesap bilgileri sorulacak");
      } else if (session) {
        await turnOn(sb, permP);
      } else {
        const box = card(`<form class="push-login" id="pushLogin">
            <label>E-posta<input id="pushEmail" type="email" autocomplete="username" required></label>
            <label>Parola<input id="pushPass" type="password" autocomplete="current-password" required></label>
            <button class="btn btn-primary" type="submit">Analiz hesabınla giriş yap</button>
            <p class="push-err" id="pushErr" hidden></p></form>`);
        box.querySelector("#pushLogin").addEventListener("submit", async (e) => {
          e.preventDefault();
          const err = box.querySelector("#pushErr");
          const { error } = await sb.auth.signInWithPassword({ email: box.querySelector("#pushEmail").value.trim(), password: box.querySelector("#pushPass").value });
          if (error) {
            err.textContent = /invalid login/i.test(error.message) ? "E-posta veya parola doğru değil." : error.message;
            err.hidden = false;
            return;
          }
          // iPhone izin penceresini yalnızca bir dokunuşla açar: girişten sonra ayrı düğme
          card(`<button class="btn btn-primary" id="pushOn" type="button">Bildirimleri aç</button><p class="push-err" id="pushErr" hidden></p>`)
            .querySelector("#pushOn").addEventListener("click", (ev) => turnOn(sb).catch((x) => {
              const e2 = document.querySelector("#pushSetup #pushErr");
              e2.textContent = x.message;
              e2.hidden = false;
              ev.target.disabled = false;
            }));
        });
      }
    } catch (x) {
      toast(x.message || "Bildirim ayarlanamadı");
    } finally {
      btn.disabled = false;
      await paint();
    }
  });

  const s = await paint();
  // Açıksa abonelik her açılışta hesaba yeniden yazılır (iPhone aboneliği yenileyebilir)
  if (s === "on") {
    const sb = await sbP;
    const { data: { session } } = await sb.auth.getSession();
    const sub = await currentSub();
    if (session && sub) save(sb, sub).catch((e) => console.warn(e));
  }
}

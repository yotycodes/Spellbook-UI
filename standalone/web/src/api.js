// standalone/web/src/api.js
// DOM helpers, typed fetch wrappers, formatting, toast notifications, clipboard.

export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

export const api = async (path, opts = {}) => {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const data = await r.json();
      msg = data.detail ? (Array.isArray(data.detail) ? JSON.stringify(data.detail) : String(data.detail)) : msg;
    } catch (_) { }
    throw new Error(msg);
  }
  return r.json();
};

export const label = (s) => String(s ?? "").replace(/^\p{Extended_Pictographic}\uFE0F?\s*/u, "");
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const fmt = (n) => Number(n || 0).toLocaleString();

export function toast(msg, kind = "ok", action = null) {
  const icon = { ok: "ph-check-circle", err: "ph-warning-circle", info: "ph-info" }[kind];
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<i class="ph-fill ${icon}"></i><span>${msg}</span>${action ? `<button class="btn btn-sm toast-act">${esc(action.label)}</button>` : ""}${kind === "err" ? `<button class="icon-btn toast-x" aria-label="Dismiss"><i class="ph ph-x"></i></button>` : ""}`;
  $("#toasts").append(el);
  const close = () => { el.classList.add("out"); setTimeout(() => el.remove(), 260); };
  if (action) el.querySelector(".toast-act").onclick = () => { action.fn(); close(); };
  if (kind === "err") el.querySelector(".toast-x").onclick = close;  // errors stay until dismissed
  else setTimeout(close, action ? 6000 : 2800);  // leave time to hit Undo
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast("Copied to clipboard", "info");
}

// In-app dialogs. The installed app's web view has no native dialog support,
// so window.confirm() always returns false and window.prompt() always returns
// null there. These replace them with a modal styled like the fix menu.
export function confirmDialog(message) {
  return new Promise((resolve) => {
    document.querySelector(".fix-menu")?.remove();
    const m = document.createElement("div");
    m.className = "fix-menu"; m.setAttribute("role", "dialog"); m.setAttribute("aria-label", "Confirm");
    m.innerHTML = `<b>${esc(message).replace(/\n/g, "<br>")}</b>
      <div class="fix-menu-row"><button class="btn btn-sm" data-x="cancel">Cancel</button><button class="btn btn-sm btn-primary" data-x="go">Confirm</button></div>`;
    m.style.position = "fixed"; m.style.left = "50%"; m.style.top = "50%"; m.style.transform = "translate(-50%, -50%)"; m.style.zIndex = "9999"; m.style.animation = "none";
    document.body.append(m);
    const done = (v) => { m.remove(); document.removeEventListener("keydown", esc_, true); resolve(v); };
    const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(false); } };
    document.addEventListener("keydown", esc_, true);
    m.addEventListener("click", (e) => {
      const x = e.target.closest("[data-x]"); if (!x) return;
      done(x.dataset.x === "go");
    });
    m.querySelector('[data-x="go"]')?.focus();
  });
}

export function promptDialog(message, def = "") {
  return new Promise((resolve) => {
    document.querySelector(".fix-menu")?.remove();
    const m = document.createElement("div");
    m.className = "fix-menu"; m.setAttribute("role", "dialog"); m.setAttribute("aria-label", "Input");
    m.innerHTML = `<b>${esc(message).replace(/\n/g, "<br>")}</b>
      <input type="text" data-input value="${esc(def)}">
      <div class="fix-menu-row"><button class="btn btn-sm" data-x="cancel">Cancel</button><button class="btn btn-sm btn-primary" data-x="go">OK</button></div>`;
    m.style.position = "fixed"; m.style.left = "50%"; m.style.top = "50%"; m.style.transform = "translate(-50%, -50%)"; m.style.zIndex = "9999"; m.style.animation = "none";
    document.body.append(m);
    const input = m.querySelector("[data-input]");
    const done = (v) => { m.remove(); document.removeEventListener("keydown", esc_, true); resolve(v); };
    const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(null); } };
    document.addEventListener("keydown", esc_, true);
    m.addEventListener("click", (e) => {
      const x = e.target.closest("[data-x]"); if (!x) return;
      done(x.dataset.x === "go" ? input.value : null);
    });
    input?.addEventListener("keydown", (e) => { if (e.key === "Enter") done(input.value); });
    input?.focus(); input?.select();
  });
}

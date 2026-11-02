// standalone/web/src/main.js
// Main entry point: routing, global keyboard shortcuts, status monitors, accessibility, bootstrapping.

import { $, $$, api, esc, toast, confirmDialog } from "./api.js";
import { state, savePrefs, gen, forge } from "./state.js";
import { closeInspector, select, sendToKrita } from "./components/inspector.js";
import { togglePalette } from "./components/command-palette.js";
import { closeLightbox, lbStep, zoom } from "./components/lightbox.js";
import { fillSelect, renderFilters, renderCollections, goPage, setCardSize, runSearch } from "./views/library.js";
import { loadGenOptions, renderGallery, renderGenStatus, runGen, startPolling, openInGenerate } from "./views/generate.js";
import { renderHistory } from "./views/interrogate.js";
import { loadSettings } from "./views/settings.js";

/* ------------------------------------------------------------------ views & router */
export function showView(name) {
  if (state.view === "library" && name !== "library") {
    state.libScroll = $("#gridWrap")?.scrollTop || 0;
    state.libReopen = $("#app")?.classList.contains("inspecting") ? state.sel : -1;
  }
  const back = state.view !== "library" && name === "library";
  state.view = name; savePrefs();
  $$(".rail-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  if (name !== "library") closeInspector();
  if (name === "collections") renderCollections();
  if (name === "generate") { if (!gen.opts?.online) loadGenOptions(); renderGallery({ refresh: !gen.galLoaded }); }
  if (name === "library") {
    $("#gridWrap")?.focus?.({ preventScroll: true });
    if (back) requestAnimationFrame(() => {
      if (state.libScroll != null && $("#gridWrap")) $("#gridWrap").scrollTop = state.libScroll;
      if (state.libReopen >= 0 && state.items[state.libReopen]) select(state.libReopen);
    });
  }
  if (name === "settings") loadSettings();
  if (name === "generate") { gen.unseen = 0; gen.pillHidden = false; }
  renderGenStatus?.();
}

$$(".rail-btn").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));



/* ------------------------------------------------------------------ keyboard */
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
  const genOn = $("#view-generate")?.classList.contains("is-active");
  if (!$("#compare")?.hidden) { if (e.key === "Escape") $("#compare").hidden = true; return; }
  if (!$("#cmpGrid")?.hidden && $("#lightbox")?.hidden) { if (e.key === "Escape") $("#cmpGridClose")?.click(); return; }
  if (!$("#poseModal")?.hidden) { if (e.key === "Escape") $("#poseModal").hidden = true; return; }
  if (!$("#lightbox")?.hidden) {
    if (e.key === "Escape") closeLightbox();
    else if (!e.metaKey && !e.ctrlKey && zoom.key(e)) e.preventDefault();
    else if (e.key.toLowerCase() === "f" && !$("#lightbox").classList.contains("viewer")) $("#lbStar")?.click();
    else if (e.key === "ArrowLeft") lbStep(-1);
    else if (e.key === "ArrowRight") lbStep(1);
    return;
  }
  if (!$("#help")?.hidden) { if (e.key === "Escape" || e.key === "?") { e.preventDefault(); $("#help").hidden = true; } return; }
  if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); togglePalette(); return; }
  if (e.key === "?" && !typing) { e.preventDefault(); if ($("#help")) $("#help").hidden = false; return; }
  if (!$("#palette")?.hidden) return;
  if (genOn && e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); runGen(); return; }
  if (e.key === "Escape") { if (typing) document.activeElement?.blur(); else closeInspector(); return; }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  const libraryOn = $("#view-library")?.classList.contains("is-active");
  if (["1", "2", "3", "4", "5"].includes(e.key)) { showView(["generate", "library", "collections", "interrogate", "settings"][Number(e.key) - 1]); return; }
  if (!libraryOn) return;
  if (e.key === "/") { e.preventDefault(); $("#q")?.focus(); $("#q")?.select(); }
  else if (e.key === "ArrowRight" || e.key === "ArrowLeft" || e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const cols = getComputedStyle($("#grid")).gridTemplateColumns.split(" ").length;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[e.key];
    select(Math.max(0, Math.min(state.items.length - 1, (state.sel < 0 ? 0 : state.sel + step))));
  }
  else if (e.key === "]") goPage(state.page + 1);
  else if (e.key === "-") setCardSize(state.cardSize === "l" ? "m" : "s");
  else if (e.key === "=" || e.key === "+") setCardSize(state.cardSize === "s" ? "m" : "l");
  else if (e.key === "[") goPage(state.page - 1);
  else if (e.key.toLowerCase() === "k" && state.record) sendToKrita();
  else if (e.key.toLowerCase() === "g" && state.record) openInGenerate(state.record.id);
  else if (e.key.toLowerCase() === "s" && state.record) $("#iSave")?.click();
});

/* ------------------------------------------------------------------ krita status */
export async function refreshKrita() {
  if (document.hidden) return;
  try {
    const s = await api("/api/krita/status");
    const el = $("#kritaStatus");
    if (!el) return;
    el.classList.toggle("online", s.online);
    el.classList.toggle("nodoc", s.online && !s.document);
    el.title = !s.online ? "Krita not connected" : s.document ? "Krita connected" : "Krita connected, no document open";
    const sr = $("#kritaSr");
    if (sr) sr.textContent = !s.online ? "not connected" : s.document ? "connected" : "connected, no document open";
  } catch {}
}
setInterval(refreshKrita, 8000);

/* ------------------------------------------------------------------ forge status */
export const FORGE_COPY = {
  on: ["Forge is on", "Ready to generate", "Stop Forge", "ph-power"],
  busy: ["Forge is busy", "Generating or loading models…", "Stop Forge", "ph-circle-notch spin"],
  off: ["Forge is off", "Start Forge to generate images", "Start Forge", "ph-power"],
  starting: ["Forge is starting", "", "Starting…", "ph-circle-notch spin"],
  stopping: ["Forge is stopping", "", "Stopping…", "ph-circle-notch spin"],
  "no-api": ["Forge is on without its API", "Restart Forge with its API enabled", "Stop Forge", "ph-power"],
  crashed: ["Forge stopped while starting", "See forge.log for details", "Start Forge", "ph-power"],
};

export async function refreshForge() {
  if (document.hidden && !["starting", "stopping"].includes(forge.state)) return;
  let s;
  try { s = await api("/api/forge/status"); } catch { return; }
  const prev = forge.state;
  forge.state = s.state;
  const [title, detail, btn, icon] = FORGE_COPY[s.state] || FORGE_COPY.off;
  const extra = s.state === "starting" ? `${s.detail || ""} ${s.elapsed ? Math.round(s.elapsed) + "s" : ""}`.trim()
    : s.state === "crashed" ? (s.detail || "See forge.log for details") : detail;
  for (const el of [$("#forgeStatus"), $("#forgePill")]) {
    if (!el) continue;
    el.classList.toggle("online", s.state === "on" || s.state === "busy");
    el.classList.toggle("nodoc", ["starting", "stopping", "no-api"].includes(s.state));
    el.classList.toggle("busy", ["starting", "stopping", "busy"].includes(s.state));
  }
  const forgeSr = $("#forgeSr"); if (forgeSr) forgeSr.textContent = title;
  const forgeStatus = $("#forgeStatus");
  if (forgeStatus) {
    forgeStatus.title = (s.state === "on" || s.state === "busy")
      ? "Forge is running. Spellbook UI manages Forge; click to stop it."
      : s.state === "off" || s.state === "crashed" ? "Click to start Forge from Spellbook UI." : title;
  }
  const forgeState = $("#forgeState"); if (forgeState) forgeState.textContent = title;
  const forgeDetail = $("#forgeDetail"); if (forgeDetail) forgeDetail.textContent = extra;
  const tb = $("#forgeToggle");
  if (tb) {
    tb.innerHTML = `<i class="ph ${icon}"></i><span>${btn}</span>`;
    tb.disabled = ["starting", "stopping"].includes(s.state);
    tb.title = (s.state === "on" || s.state === "busy")
      ? "Stop the shared Forge server. Spellbook UI is its primary controller."
      : s.state === "off" || s.state === "crashed" ? "Start Forge from Spellbook UI." : title;
    tb.classList.toggle("btn-primary", s.state === "off" || s.state === "crashed");
  }
  if (!["on", "busy"].includes(prev) && ["on", "busy"].includes(s.state)) { toast("Forge is on"); loadGenOptions(); }
  if (["on", "busy"].includes(prev) && s.state === "off") loadGenOptions();
  clearTimeout(forge.timer);
  forge.timer = setTimeout(refreshForge, ["starting", "stopping"].includes(s.state) ? 1500 : 8000);
}

export async function toggleForge() {
  if (["starting", "stopping"].includes(forge.state)) return;
  try {
    if (["on", "busy", "no-api"].includes(forge.state)) {
      if ((gen.polling || forge.state === "busy") && !(await confirmDialog("An image may be generating or Forge may be loading a model. Stop Forge anyway?"))) return;
      await api("/api/forge/stop", { method: "POST" });
      toast("Stopping Forge", "info");
    } else {
      let r = await api("/api/forge/start", { json: { force: false } });
      if (!r.ok) return toast(esc(r.error), "err");
      toast(r.already ? "Forge is already running" : "Starting Forge. The first start can take a couple of minutes.", "info");
    }
    refreshForge();
  } catch (err) {
    toast(`Forge request failed: ${esc(err?.message || String(err))}`, "err");
  }
}

$("#forgeStatus")?.addEventListener("click", toggleForge);
$("#forgeToggle")?.addEventListener("click", toggleForge);

/* ------------------------------------------------------------------ a11y helpers */
export function a11yPass(root = document) {
  $$("i.ph, i.ph-fill", root).forEach((i) => i.setAttribute("aria-hidden", "true"));
  $$("button[title]:not([aria-label])", root).forEach((b) => {
    if (!b.textContent.trim()) b.setAttribute("aria-label", b.title.replace(/\s+\(.*\)$/, ""));
  });
}
const a11yRoots = new Set();
new MutationObserver((muts) => {
  muts.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) a11yRoots.add(n); }));
  if (a11yPass.queued) return;
  a11yPass.queued = true;
  requestAnimationFrame(() => {
    a11yPass.queued = false;
    if (a11yRoots.size > 12) a11yPass(document.body);
    else a11yRoots.forEach((n) => { if (n.isConnected) a11yPass(n); });
    a11yRoots.clear();
  });
}).observe(document.body, { childList: true, subtree: true });
a11yPass();

document.addEventListener("keydown", (e) => {
  const t = e.target.closest?.('[role="button"]');
  if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); t.click(); }
});

export function nameFields(root = document) {
  $$("textarea, input:not([type=file]):not([type=checkbox]), select", root).forEach((f) => {
    if (f.getAttribute("aria-label") || f.labels?.length) return;
    let name = "";
    const row = f.closest(".slider-row");
    if (row) name = row.querySelector("span")?.textContent.trim() + (f.type === "number" ? " value" : "");
    if (!name) {
      let p = f.previousElementSibling;
      while (p && !p.classList?.contains("label-row") && p.tagName !== "SUMMARY") p = p.previousElementSibling;
      name = !p ? "" : p.tagName === "SUMMARY" ? (p.firstChild?.textContent || "").trim() : (p.querySelector("span")?.textContent || p.firstChild?.textContent || "").trim();
    }
    if (!name && f.closest("details")) name = f.closest("details").querySelector("summary")?.firstChild?.textContent.trim();
    name = name || f.placeholder?.replace(/…$/, "") || f.id;
    if (name) f.setAttribute("aria-label", name);
  });
}

export function syncStates(root = document) {
  $$(".tab", root).forEach((t) => { t.setAttribute("role", "tab"); t.setAttribute("aria-selected", String(t.classList.contains("is-on"))); });
  $$(".rail-btn", root).forEach((b) => (b.classList.contains("is-active") ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  $$(".seg button, .tagchip, .gpose, .pack-pose, .pose, .style-pick-chip, .tg-head, #gSize button", root)
    .forEach((b) => b.setAttribute("aria-pressed", String(b.classList.contains("is-on"))));
}

new MutationObserver((muts) => {
  let states = false;
  muts.forEach((m) => {
    if (m.type === "attributes") { states = true; return; }
    m.addedNodes.forEach((n) => { if (n.nodeType === 1) { nameFields(n); states = true; } });
  });
  if (states && !syncStates.queued) { syncStates.queued = true; requestAnimationFrame(() => { syncStates.queued = false; syncStates(); }); }
}).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
nameFields(); syncStates();

$("#q")?.setAttribute("aria-label", "Search prompts, tags or characters");
$("#pgInput")?.setAttribute("aria-label", "Page number");

export const overlayFocus = new Map();
["#lightbox", "#compare", "#palette", "#help", "#poseModal"].forEach((sel) => {
  const el = $(sel);
  if (!el) return;
  new MutationObserver(() => {
    const open = !el.hidden;
    if (open && !overlayFocus.has(el)) {
      overlayFocus.set(el, document.activeElement);
      const appEl = $("#app");
      if (appEl) appEl.inert = true;
      setTimeout(() => {
        if (el.contains(document.activeElement)) return;
        const target = el.querySelector("input") || [...el.querySelectorAll("button")].find((b) => b.offsetParent !== null) || el.querySelector("[tabindex]");
        target?.focus();
      }, 0);
    } else if (!open && overlayFocus.has(el)) {
      const prev = overlayFocus.get(el); overlayFocus.delete(el);
      if (!overlayFocus.size) {
        const appEl = $("#app");
        if (appEl) appEl.inert = false;
      }
      prev?.focus?.();
    }
  }).observe(el, { attributes: true, attributeFilter: ["hidden"] });
});

/* ------------------------------------------------------------------ prompt editing: tag autocomplete + ⌘↑/⌘↓ weights */
export const ac = { el: null, items: [], sel: 0, cache: new Map(), timer: null };

export function tokenAt(ta) {
  const v = ta.value, end = ta.selectionStart;
  const start = Math.max(v.lastIndexOf(",", end - 1), v.lastIndexOf("\n", end - 1)) + 1;
  return { start, end, text: v.slice(start, end).replace(/^\s+/, "") };
}

export function closeAc() {
  const pop = $("#acPop");
  if (pop) pop.hidden = true;
  ac.el = null;
}

export async function suggest(ta) {
  const t = tokenAt(ta).text;
  if (t.length < 2 || /[<:(]/.test(t)) return closeAc();
  const key = t.toLowerCase();
  let list = ac.cache.get(key);
  if (!list) { list = await api(`/api/tags?q=${encodeURIComponent(key)}`).catch(() => []); ac.cache.set(key, list); }
  if (document.activeElement !== ta || tokenAt(ta).text.toLowerCase() !== key) return;
  if (!list.length || (list.length === 1 && list[0] === key)) return closeAc();
  ac.el = ta; ac.items = list; ac.sel = 0;
  const r = ta.getBoundingClientRect();
  const pop = $("#acPop");
  if (!pop) return;
  pop.innerHTML = list.map((n, i) => `<li data-i="${i}" class="${i === 0 ? "is-on" : ""}">${esc(n).replace(esc(key), `<b>${esc(key)}</b>`)}</li>`).join("");
  pop.style.left = `${r.left + 8}px`; pop.style.top = `${Math.min(r.bottom + 4, innerHeight - 280)}px`;
  pop.hidden = false;
}

export function acceptAc(i = ac.sel) {
  const ta = ac.el, tag = ac.items[i]; if (!ta || !tag) return;
  const { start, end } = tokenAt(ta);
  const lead = ta.value.slice(start, end).match(/^\s*/)[0] || (start > 0 ? " " : "");
  const ins = tag.replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const rest = ta.value.slice(end);
  ta.value = ta.value.slice(0, start) + lead + ins + (rest.trimStart().startsWith(",") ? "" : ", ") + rest.replace(/^\s+/, "");
  const pos = start + lead.length + ins.length + 2;
  ta.setSelectionRange(pos, pos);
  ta.dispatchEvent(new Event("input")); ta.dispatchEvent(new Event("change"));
  closeAc();
}

export function weightSelection(ta, delta) {
  const v = ta.value;
  let a = ta.selectionStart, b = ta.selectionEnd;
  if (a === b) {
    a = Math.max(v.lastIndexOf(",", a - 1), v.lastIndexOf("\n", a - 1)) + 1;
    const c = v.slice(b).search(/[,\n]/);
    b = c < 0 ? v.length : b + c;
  }
  while (a < b && /\s/.test(v[a])) a++;
  while (b > a && /\s/.test(v[b - 1])) b--;
  const sel = v.slice(a, b); if (!sel) return;
  const m = sel.match(/^\((.+):([\d.]+)\)$/);
  const inner = m ? m[1] : sel;
  const w = Math.round(((m ? Number(m[2]) : 1) + delta) * 100) / 100;
  const out = Math.abs(w - 1) < 0.001 ? inner : `(${inner}:${Number(w.toFixed(2))})`;
  ta.value = v.slice(0, a) + out + v.slice(b);
  ta.setSelectionRange(a, a + out.length);
  ta.dispatchEvent(new Event("input")); ta.dispatchEvent(new Event("change"));
}

["#gPrompt", "#gNeg", "#kPrompt", "#kNeg", "#pTags", "#irChar", "#irPrompt"].forEach((id) => {
  document.addEventListener("input", (e) => { if (e.target.matches?.(id)) { clearTimeout(ac.timer); ac.timer = setTimeout(() => suggest(e.target), 120); } });
});

document.addEventListener("keydown", (e) => {
  const ta = e.target;
  if (!(ta instanceof HTMLTextAreaElement)) return;
  if ((e.metaKey || e.ctrlKey) && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); weightSelection(ta, e.key === "ArrowUp" ? 0.05 : -0.05); return; }
  const acPop = $("#acPop");
  if (!acPop || acPop.hidden || ac.el !== ta) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); ac.sel = (ac.sel + (e.key === "ArrowDown" ? 1 : -1) + ac.items.length) % ac.items.length;
    $$("#acPop li").forEach((li, i) => li.classList.toggle("is-on", i === ac.sel));
  } else if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); acceptAc(); }
  else if (e.key === "Escape") { e.stopPropagation(); closeAc(); }
}, true);

$("#acPop")?.addEventListener("mousedown", (e) => { const li = e.target.closest("[data-i]"); if (li) { e.preventDefault(); acceptAc(Number(li.dataset.i)); } });
document.addEventListener("focusout", (e) => { if (e.target === ac.el) setTimeout(closeAc, 120); });

/* ------------------------------------------------------------------ "while you were away" */
export async function awaySummary() {
  const list = await api("/api/gen/history").catch(() => []);
  if (!gen.galLoaded) { gen.gallery = list; gen.galLoaded = true; }
  let last = 0; try { last = Number(localStorage.getItem("pl-seen") || 0); } catch {}
  const fresh = last ? list.filter((g) => (g.time || 0) > last) : [];
  try { localStorage.setItem("pl-seen", String(Date.now() / 1000)); } catch {}
  if (fresh.length) toast(`${fresh.length} new image${fresh.length > 1 ? "s" : ""} finished while you were away. They're in Generate.`, "info");
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  refreshKrita();
  refreshForge();
});
window.addEventListener("beforeunload", () => { try { localStorage.setItem("pl-seen", String(Date.now() / 1000)); } catch {} });

/* ------------------------------------------------------------------ boot */
function setBootStage(text) { const el = $("#bootStage"); if (el) el.textContent = text; }
function hideBoot() { const el = $("#bootOverlay"); if (!el) return; el.classList.add("done"); setTimeout(() => el.remove(), 400); }

(async function boot() {
  try {
    state.meta = await api("/api/meta");
  } catch (e) {
    const pagerCount = $("#pagerCount");
    if (pagerCount) pagerCount.textContent = "Library failed to load";
    toast(esc(e.message), "err");
    hideBoot();
    return;
  }
  setBootStage("Loading your library…");
  fillSelect($("#ipreset"), state.meta.presets, state.meta.presets.find((p) => p.includes("Toon Pin-up Sheet")) || state.meta.presets[0]);
  fillSelect($("#iengine"), state.meta.engines, state.meta.default_engine);
  if (!state.meta.ratings.includes(state.rating)) state.rating = "SFW";
  if (!state.meta.sorts.includes(state.sort)) state.sort = "Most reactions";
  renderFilters();
  refreshKrita();
  refreshForge();
  renderHistory();
  setCardSize(state.cardSize || "m");
  awaySummary();
  const qList = $("#qList");
  if (qList) qList.innerHTML = (state.meta.heroes || []).slice(0, 400).map(([h, n]) => `<option value="${esc(h)}">${n} prompts</option>`).join("");
  const tab = $(`.tab[data-tab="${state.tab}"]`); if (tab && state.tab !== "krita") tab.click();
  if (state.view && state.view !== "library") showView(state.view);
  await runSearch();
  hideBoot();
})();

startPolling();

// standalone/web/src/views/settings.js
// Settings view: connections, folders, prompt models, appearance themes, density & dark mode.

import { $, $$, api, esc, toast } from "../api.js";
import { state, savePrefs, gen, themeUi } from "../state.js";
import { showView } from "../main.js";
import { renderGallery } from "./generate.js";
import { newSearch } from "./library.js";

export const SET_CONN = [
  ["forge", "Forge", "ph-power", (c) => c.url, "Generates images. Start and stop it with the Forge switch in the rail."],
  ["krita", "Krita", "ph-paint-brush", (c) => c.url, "Receives prompts, poses and images through the AI Prompt Bridge add-on."],
  ["ollama", "Ollama (local AI)", "ph-cpu", (c) => `${c.url} · ${c.model}`, "Writes prompts from images on your Mac, offline. Works for mature content."],
  ["claude", "Claude API", "ph-sparkle", (c) => c.key_set ? `${c.key_hint || "key set"} · ${c.key_source} · ${c.model}` : "No key yet", "Best prompt writing in Interrogate. SFW only."],
];

export function paintTheme(id) {
  if (id === themeUi.def) delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = id;
  syncTitlebar();
}

export function syncTitlebar() {
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
  const metaTheme = $('meta[name="theme-color"]');
  if (metaTheme) metaTheme.content = bg;
  if (/^#[0-9a-f]{6}$/i.test(bg)) api("/api/window/titlebar", { json: { color: bg } }).catch(() => {});
}

export function previewTheme(id) {
  if (id === themeUi.saved) return cancelThemePreview();
  themeUi.preview = id; paintTheme(id); renderThemes();
}

export function applyTheme() {
  const id = themeUi.preview; if (!id) return;
  themeUi.saved = id; themeUi.preview = null;
  try { localStorage.setItem("pl-theme", id); } catch {}
  renderThemes(); toast(`Theme: ${esc(themeUi.list.find((t) => t.id === id)?.name || id)}`, "info");
}

export function cancelThemePreview() {
  if (!themeUi.preview) return;
  themeUi.preview = null; paintTheme(themeUi.saved); renderThemes();
}

export function themeCard(t) {
  const c = t.colors, on = t.id === (themeUi.preview || themeUi.saved);
  const stateLabel = t.id === themeUi.preview ? `<span class="theme-state is-preview">Previewing</span>` : t.id === themeUi.saved ? `<span class="theme-state"><i class="ph-fill ph-check-circle"></i>Applied</span>` : "";
  return `<button class="theme-opt${on ? " is-on" : ""}" role="radio" aria-checked="${on}" data-theme-id="${t.id}">
    <span class="theme-mini" style="background:${c.bg};border-color:${c["line-2"]}" aria-hidden="true">
      <span class="tm-rail" style="background:${c.surface}"><i style="background:${c["accent-soft"]}"></i><i style="background:${c["line-2"]}"></i><i style="background:${c["line-2"]}"></i></span>
      <span class="tm-panel" style="background:${c.surface};border-color:${c["line-2"]}">
        <i class="tm-h" style="background:${c.text}"></i><i class="tm-l" style="background:${c["text-2"]}"></i>
        <span class="tm-chip" style="background:${c["accent-soft"]};color:${c.accent}">Aa</span>
        <span class="tm-btn" style="background:${c["accent-fill"]};color:${c["accent-ink"]}">Generate</span>
      </span>
      <span class="tm-art" style="background:${c["surface-3"]}"></span>
    </span>
    <span class="theme-name">${esc(t.name)}${stateLabel}</span><span class="theme-mood">${esc(t.mood)}</span></button>`;
}

export function renderThemes() {
  const setThemeEl = $("#setTheme");
  if (!setThemeEl) return;
  setThemeEl.innerHTML = themeUi.list.map(themeCard).join("");
  const p = themeUi.list.find((t) => t.id === themeUi.preview);
  const bar = $("#setThemeBar");
  if (bar) bar.hidden = !p;
  if (p) $("#setThemeBarText").innerHTML = `Previewing <b>${esc(p.name)}</b> on the whole app.`;
}

$("#setTheme")?.addEventListener("click", (e) => { const b = e.target.closest("[data-theme-id]"); if (b) previewTheme(b.dataset.themeId); });
$("#setThemeApply")?.addEventListener("click", applyTheme);
$("#setThemeCancel")?.addEventListener("click", cancelThemePreview);
$("#setThemeReset")?.addEventListener("click", () => { previewTheme(themeUi.def); if (themeUi.preview) applyTheme(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && themeUi.preview) cancelThemePreview(); });

fetch("themes.json").then((r) => r.json()).then((d) => {
  themeUi.list = d.themes; themeUi.def = d.default;
  const cur = document.documentElement.dataset.theme || d.default;
  themeUi.saved = d.themes.some((t) => t.id === cur) ? cur : d.default;
  if (themeUi.saved !== cur) { paintTheme(themeUi.saved); try { localStorage.setItem("pl-theme", themeUi.saved); } catch {} }
  else syncTitlebar();
  renderThemes();
}).catch(() => {});

export async function loadSettings() {
  const s = await api("/api/settings").catch((e) => (toast(esc(e.message), "err"), null));
  if (s) renderSettings(s);
}

export function renderSettings(s) {
  gen.settings = s;
  $("#setConn").innerHTML = SET_CONN.map(([id, name, icon, detail, note]) => {
    const c = s.connections[id], on = id === "claude" ? c.key_set : c.online;
    const stateLabel = on ? (id === "claude" ? "key saved" : "connected") : (id === "claude" ? "not set" : "not running");
    return `<div class="set-row">
      <div class="set-main"><b><i class="ph ${icon}"></i>${name}<span class="set-dot ${on ? "on" : ""}" aria-hidden="true"></span><span class="muted small">${stateLabel}</span></b>
        <span class="muted">${note}</span><code>${esc(detail(c))}</code>
        ${id === "claude" ? `<div class="set-key"><input class="input" id="setClaudeKey" type="password" placeholder="${c.key_set ? "Paste a new key to replace it" : "Paste your key (sk-ant-…)"}" autocomplete="off" aria-label="Claude API key">
          <button class="btn btn-sm" data-act="savekey">Save to Keychain</button>${c.key_set && c.key_source === "Keychain" ? `<button class="btn btn-sm danger" data-act="delkey">Remove</button>` : ""}</div>` : ""}
        ${id === "ollama" && c.models.length ? `<label class="field set-inline"><span>Model</span><select class="input" id="setOllamaModel">${c.models.map((m) => `<option ${m === c.model ? "selected" : ""}>${esc(m)}</option>`).join("")}${c.models.includes(c.model) ? "" : `<option selected>${esc(c.model)}</option>`}</select></label>` : ""}
      </div>
      <div class="set-ctl">
        <button class="btn btn-sm" data-test="${id}">Test</button></div>
    </div>`;
  }).join("");
  $("#setFolders").innerHTML = s.folders.map((f) => `<div class="set-row">
      <div class="set-main"><b>${esc(f.label)}${f.exists ? "" : `<span class="muted small"> · ${f.id === "export_dir" ? "created on first export" : "missing"}</span>`}</b><span class="muted">${esc(f.note)}</span><code title="${esc(f.path)}">${esc(f.path.replace(/^\/Users\/[^/]+/, "~"))}</code></div>
      <div class="set-ctl"><button class="btn btn-sm" data-reveal="${esc(f.path)}" ${f.exists ? "" : "disabled"}><i class="ph ph-folder-open"></i>Show in Finder</button>
        ${f.editable ? `<button class="btn btn-sm" data-change="${f.id}"><i class="ph ph-pencil-simple"></i>Change…</button>` : ""}</div>
    </div>`).join("");
  $("#setGen").value = s.interrogate.general_threshold; $("#setChar").value = s.interrogate.character_threshold;
  $("#setAbout").textContent = `Spellbook UI ${s.app.version || ""} · app data in ${s.app.data_dir.replace(/^\/Users\/[^/]+/, "~")}`;
}

export async function saveSettings(changes, extra = {}) {
  const r = await api("/api/settings", { json: { changes, ...extra } }).catch((e) => (toast(esc(e.message), "err"), null));
  if (r) renderSettings(r.settings);
  return r;
}

$("#view-settings")?.addEventListener("click", async (e) => {
  const rv = e.target.closest("[data-reveal]"); if (rv) { api("/api/settings/reveal", { json: { path: rv.dataset.reveal } }).catch((x) => toast(esc(x.message), "err")); return; }
  const t = e.target.closest("[data-test]");
  if (t) {
    t.disabled = true; const r = await api("/api/settings/test", { json: { what: t.dataset.test } }).catch((x) => ({ ok: false, message: x.message })); t.disabled = false;
    toast(esc(r.message), r.ok ? "info" : "err"); loadSettings(); return;
  }
  const ch = e.target.closest("[data-change]");
  if (ch) {
    const f = gen.settings.folders.find((x) => x.id === ch.dataset.change);
    const pick = await api("/api/settings/choose-folder", { json: { current: f.path, prompt: `Choose the folder for ${f.label.toLowerCase()}` } }).catch((x) => (toast(esc(x.message), "err"), null));
    if (!pick || pick.cancelled || pick.path === f.path) return;
    let move = false;
    if (f.id === "gen_dir") move = confirm(`Move your existing images into the new folder too?\n\nOK: move them (the gallery keeps showing them).\nCancel: leave them in the old folder (the gallery starts empty).`);
    const r = await saveSettings({ [f.id]: pick.path }, { move_outputs: move });
    if (r) {
      toast(`${esc(f.label)} → ${esc(pick.path.replace(/^\/Users\/[^/]+/, "~"))}${r.moved ? ` · moved ${r.moved} files` : ""}`);
      if (f.id === "gen_dir") renderGallery();
      if (f.id === "library_path") newSearch?.();
    }
    return;
  }
  if (e.target.closest('[data-act="savekey"]')) {
    const key = $("#setClaudeKey").value.trim(); if (!key) return toast("Paste a key first", "err");
    const r = await api("/api/settings/claude-key", { json: { key } }).catch((x) => (toast(esc(x.message), "err"), null));
    if (r) { renderSettings(r.settings); toast("Claude key saved to your Keychain"); }
    return;
  }
  if (e.target.closest('[data-act="delkey"]')) {
    if (!confirm("Remove the Claude API key from your Keychain?")) return;
    const r = await api("/api/settings/claude-key", { json: { key: "" } }).catch((x) => (toast(esc(x.message), "err"), null));
    if (r) { renderSettings(r.settings); toast("Claude key removed", "info"); }
  }
  const d = e.target.closest(".set-card [data-d]");
  if (d) { state.density = d.dataset.d; savePrefs(); updateDensityButtons(); return; }
  const dm = e.target.closest(".set-card [data-dm]");
  if (dm) { state.darkMode = dm.dataset.dm; savePrefs(); updateDarkModeButtons(); return; }
});

$("#view-settings")?.addEventListener("change", (e) => {
  if (e.target.id === "setOllamaModel") saveSettings({ ollama_model: e.target.value }).then((r) => r && toast(`Ollama model: ${esc(e.target.value)}`));
  if (e.target.id === "setGen") saveSettings({ general_threshold: Number(e.target.value) });
  if (e.target.id === "setChar") saveSettings({ character_threshold: Number(e.target.value) });
});

$("#setRefresh")?.addEventListener("click", loadSettings);
document.addEventListener("keydown", (e) => { if (e.metaKey && e.key === ",") { e.preventDefault(); showView("settings"); } });

export function updateDensityButtons() {
  const d = state.density || "comfortable";
  document.documentElement.dataset.density = d;
  $$(".set-card [data-d]").forEach((b) => {
    const on = b.dataset.d === d;
    b.setAttribute("aria-checked", String(on));
    b.classList.toggle("is-on", on);
  });
}

export function updateDarkModeButtons() {
  const dm = state.darkMode || "auto";
  $$(".set-card [data-dm]").forEach((b) => {
    const on = b.dataset.dm === dm;
    b.setAttribute("aria-checked", String(on));
    b.classList.toggle("is-on", on);
  });
}

updateDensityButtons();
updateDarkModeButtons();

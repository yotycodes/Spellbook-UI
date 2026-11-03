// Styles manager: list / create / edit / adopt / delete "your styles", opened from the Generate tab's
// Style card (+ button). Styles are JSON files in your styles folder; Krita-origin styles merge in
// read-only and can be adopted (copied into your folder, where they shadow the original) from here.
import { $, $$, api, esc, toast, confirmDialog } from "../api.js";
import { gen } from "../state.js";

// mirrors the Forge-label values of lib_pl/kstyles.py SAMPLERS / SCHEDULERS — the server validates ids
const SAMPLERS = ["Euler", "Euler a", "DPM++ 2M", "DPM++ 2M SDE", "DPM++ SDE", "DPM++ 3M SDE",
  "LCM", "DDIM", "UniPC", "Heun", "DPM2", "DPM2 a", "LMS"];
const SCHEDULERS = ["Karras", "Normal", "Simple", "Exponential", "SGM Uniform", "Beta", "Uniform"];

const BLANK = () => ({ name: "", checkpoint: "", loras: [], style_prompt: "{prompt}", negative: "",
  sampler: "Euler a", scheduler: "Normal", steps: 25, cfg: 6, clip_skip: 2, origin: "spellbook", file: "" });

let overlay = null, styles = [], dir = "", editing = null;
let cbs = { onChanged: () => {}, onPickStyle: null };   // set by open(); onChanged refreshes the Style select

const field = (label, ctl, cls = "") => `<label class="sm-field ${cls}"><span>${label}</span>${ctl}</label>`;

function ensureOverlay() {
  if (overlay) return;
  overlay = document.createElement("div");
  overlay.className = "styles-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `<div class="styles-box" role="dialog" aria-label="Your styles"></div>`;
  document.body.append(overlay);
  overlay.addEventListener("click", (e) => { if (!e.target.closest(".styles-box")) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !overlay.hidden) close(); });
}

export function close() {
  if (overlay) { overlay.hidden = true; editing = null; }
}

export async function openStyles(next = {}) {
  cbs = { onChanged: next.onChanged || (() => {}), onPickStyle: next.onPickStyle || null };
  ensureOverlay();
  const data = await api("/api/styles").catch((e) => (toast(e.message || "Couldn't load styles", "err"), null));
  if (!data) return;
  styles = data.styles || [];
  dir = data.dir || "";
  editing = null;
  overlay.hidden = false;
  renderList();
}

// ------------------------------------------------------------------ list view
function renderList() {
  const box = $(".styles-box", overlay);
  if (!box) return;
  const n = styles.filter((s) => s.editable).length;
  box.innerHTML = `
    <div class="sm-head">
      <h2>Your styles <span class="muted">${n} saved${styles.length > n ? ` · ${styles.length - n} from Krita` : ""}</span></h2>
      <div class="sm-head-actions">
        <button class="btn" id="smFromPanel" title="Prefill a new style with the settings the Generate panel has right now"><i class="ph ph-arrow-bend-down-right"></i> From panel</button>
        <button class="btn btn-primary" id="smNew"><i class="ph ph-plus"></i> New style</button>
      </div>
    </div>
    <p class="sm-dir muted">Saved in <code>${esc(dir)}</code> — plain JSON, safe to back up.${styles.some((s) => !s.editable) ? ` Locked styles come from Krita's folder; “Adopt” copies them here and shadows the original.` : ""}</p>
    <div class="sm-list">${styles.map((s, i) => `
      <div class="sm-row${s.editable ? "" : " readonly"}" data-i="${i}">
        <div class="sm-row-main">
          <b>${esc(s.name)}</b>
          <span class="muted">${esc(s.checkpoint || "any checkpoint")}${s.loras.length ? ` · ${s.loras.length} LoRA${s.loras.length === 1 ? "" : "s"}` : ""}</span>
        </div>
        ${s.editable ? "" : `<span class="sm-lock" title="Lives in Krita's styles folder — read-only"><i class="ph ph-lock-simple"></i></span>`}
        <button class="btn btn-sm sm-adopt" data-i="${i}" ${s.editable ? "hidden" : ""}>Adopt</button>
        <button class="icon-btn sm-edit" data-i="${i}" title="Edit"><i class="ph ph-pencil-simple"></i></button>
        <button class="icon-btn sm-copy" data-i="${i}" title="Duplicate"><i class="ph ph-copy"></i></button>
        <button class="icon-btn sm-del" data-i="${i}" title="Delete" ${s.editable ? "" : "disabled"}><i class="ph ph-trash"></i></button>
      </div>`).join("") || `<p class="muted">No styles yet — start with “New style”, “From panel”, or adopt one below.</p>`}
    </div>`;
  $("#smNew").addEventListener("click", () => renderEditor(BLANK(), "New style"));
  $("#smFromPanel").addEventListener("click", () => renderEditor(fromPanel(), "New style from panel"));
  $$(".sm-adopt", box).forEach((b) => b.addEventListener("click", () => {
    const copy = cloneRow(styles[+b.dataset.i]);
    copy.file = ""; copy.origin = "spellbook";
    renderEditor(copy, "Adopting from Krita");
  }));
  $$(".sm-edit", box).forEach((b) => b.addEventListener("click", () => renderEditor(cloneRow(styles[+b.dataset.i]), "Edit style")));
  $$(".sm-copy", box).forEach((b) => {
    const copy = cloneRow(styles[+b.dataset.i]);
    copy.name = /(\d+)$/.test(copy.name) ? `${copy.name.replace(/(\d+)$/, (m) => +m + 1)}` : `${copy.name} copy`;
    copy.file = ""; copy.origin = "spellbook";
    renderEditor(copy, "Duplicate");
  });
  $$(".sm-del", box).forEach((b) => b.addEventListener("click", () => del(styles[+b.dataset.i])));
}

const cloneRow = (s) => ({ ...s, loras: (s.loras || []).map((l) => Array.isArray(l) ? { name: l[0], strength: l[1] } : { ...l }) });

// prefill from whatever the Generate panel currently holds
function fromPanel() {
  const val = (sel) => $(sel)?.value || "";
  const loras = [...val("#gPrompt").matchAll(/<lora:([^:>]+):([\d.]+)>/g)].map((m) => ({ name: m[1].trim(), strength: parseFloat(m[2]) || 1 }));
  const seen = new Set();
  return { ...BLANK(), checkpoint: val("#gModel").split(" [")[0].trim(),
    loras: loras.filter((l) => (seen.has(l.name) ? false : seen.add(l.name))),
    sampler: val("#gSampler") || "Euler a",
    scheduler: val("#gScheduler") === "Automatic" ? "Normal" : val("#gScheduler") || "Normal",
    steps: parseInt(val("#gStepsN"), 10) || 25, cfg: parseFloat(val("#gCfgN")) || 6 };
}

async function del(s) {
  if (!s?.editable) return;
  if (!(await confirmDialog(`Delete the style “${s.name}”?\nThe JSON file is removed from your styles folder.`))) return;
  const r = await api(`/api/styles/${encodeURIComponent(s.file)}`, { method: "DELETE" }).catch((e) => (toast(esc(e.message), "err"), null));
  if (!r) return;
  toast(`Style deleted: ${esc(s.name)}`, "info");
  onChangedAndList();
}

async function onChangedAndList() {
  const data = await api("/api/styles").catch(() => null);
  styles = data?.styles || styles;
  dir = data?.dir ?? dir;
  cbs.onChanged();
  renderList();
}

// ------------------------------------------------------------------ editor
function renderEditor(src, headline) {
  editing = { ...cloneRow(src) };
  const box = $(".styles-box", overlay);
  if (!box) return;
  const models = gen.opts?.models || [];
  const loras = gen.opts?.loras || [];
  const modelCtl = models.length
    ? `<select id="smCk"><option value="">any checkpoint (whatever Generate currently uses)</option>${models.map((m) =>
        `<option value="${esc(m.split(" [")[0])}" ${m.split(" [")[0] === editing.checkpoint ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>`
    : `<input id="smCk" value="${esc(editing.checkpoint)}" placeholder="e.g. waiIllustriousSDXL_v170.safetensors">`;
  box.innerHTML = `
    <div class="sm-head">
      <h2><button class="icon-btn sm-back" id="smBack" title="Back to the list"><i class="ph ph-arrow-left"></i></button> ${esc(headline || "Edit style")}</h2>
      <div class="sm-head-actions">
        ${gen.opts?.online ? `<button class="btn" id="smTry" title="Load this style into the Generate panel"><i class="ph ph-play"></i> Try it</button>` : ""}
        <button class="btn btn-primary" id="smSave"><i class="ph ph-floppy-disk"></i> Save</button>
      </div>
    </div>
    <div class="sm-grid">
      ${field("Name", `<input id="smName" value="${esc(editing.name)}" maxlength="80" placeholder="e.g. Anime · Bold outline">`)}
      ${field("Checkpoint", modelCtl)}
      ${field("Style prompt", `<textarea id="smSp" rows="4" placeholder="art-direction tags. {prompt} marks where the image's subject goes, e.g. bold outlines, cel shading, {prompt}, dramatic light"></textarea>`, "sm-wide")}
      <div class="sm-field sm-wide"><span style="opacity:.7">Hint: keep {prompt} once — that's where the user's subject lands.</span></div>
      ${field("Negative prompt", `<textarea id="smNeg" rows="2" placeholder="what the style must avoid (blurry, text, extra fingers…). Leave empty to add nothing."></textarea>`, "sm-wide")}
      ${field("Sampler", `<select id="smSampler">${SAMPLERS.map((v) => `<option value="${esc(v)}" ${editing.sampler === v ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`)}
      ${field("Scheduler", `<select id="smScheduler">${SCHEDULERS.map((v) => `<option value="${esc(v)}" ${editing.scheduler === v ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`)}
      ${field("Steps", `<input id="smSteps" type="number" min="4" max="150" value="${editing.steps || 25}">`)}
      ${field("CFG scale", `<input id="smCfg" type="number" min="1" max="20" step="0.5" value="${editing.cfg || 6}">`)}
      ${field("Clip skip", `<input id="smClip" type="number" min="0" max="5" value="${editing.clip_skip ?? 2}">`)}
      ${field("", `<span></span>`)}
    </div>
    <div class="sm-loras">
      <div class="sm-lora-head"><b>LoRAs this style carries</b>
        <button class="btn btn-sm" id="smAddLora" ${loras.length ? "" : 'title="Put .safetensors LoRAs in your LoRA folder to add them here"'}>+ Add LoRA</button>
      </div>
      <div id="smLoraRows"></div>
    </div>`;
  $("#smBack").addEventListener("click", () => { editing = null; renderList(); });
  $("#smSave").addEventListener("click", save);
  $("#smTry")?.addEventListener("click", tryIt);
  $("#smAddLora").addEventListener("click", () => { editing.loras.push({ name: "", strength: 1 }); renderLoraRows(); });
  $("#smSp").value = editing.style_prompt || "{prompt}";
  $("#smNeg").value = editing.negative || "";
  renderLoraRows();
  if (!editing.name) $("#smName").focus();
}

function renderLoraRows() {
  const wrap = $("#smLoraRows");
  if (!wrap) return;
  const installed = gen.opts?.loras || [];
  wrap.innerHTML = (editing.loras || []).map((l, i) => `
    <div class="sm-lora-row" data-i="${i}">
      <select class="sm-lora-name">${`<option value="">Choose a LoRA…</option>`}${[...new Set([...installed, l.name].filter(Boolean))].map((n) =>
        `<option ${n === l.name ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <input class="sm-lora-w" type="number" min="0" max="2" step="0.05" value="${l.strength ?? 1}" title="Strength (0–2)">
      <button class="icon-btn sm-lora-x" title="Remove"><i class="ph ph-x"></i></button>
    </div>`).join("") || `<p class="muted sm-nolora">No LoRAs — plain prompt + checkpoint.</p>`;
  $$(".sm-lora-row", wrap).forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector(".sm-lora-name").addEventListener("change", (e) => { editing.loras[i].name = e.target.value; });
    row.querySelector(".sm-lora-w").addEventListener("change", (e) => { editing.loras[i].strength = parseFloat(e.target.value); if (!Number.isFinite(editing.loras[i].strength)) editing.loras[i].strength = 1; });
    row.querySelector(".sm-lora-x").addEventListener("click", () => { editing.loras.splice(i, 1); renderLoraRows(); });
  });
}

function collect() {
  editing.name = $("#smName").value.trim();
  editing.checkpoint = $("#smCk").tagName === "SELECT" ? $("#smCk").value : $("#smCk").value.trim();
  editing.style_prompt = $("#smSp").value;
  editing.negative = $("#smNeg").value.trim();
  editing.sampler = $("#smSampler").value;
  editing.scheduler = $("#smScheduler").value;
  editing.steps = parseInt($("#smSteps").value, 10) || 25;
  editing.cfg = parseFloat($("#smCfg").value) || 6;
  editing.clip_skip = parseInt($("#smClip").value, 10) || 0;
  editing.loras = editing.loras.filter((l) => l.name);
  return editing;
}

async function save() {
  const payload = { ...collect() };
  if (!payload.name) { toast("Name your style first", "err"); $("#smName").focus(); return; }
  if (!payload.style_prompt.trim().includes("{prompt}")) {
    if (!(await confirmDialog("The style prompt has no {prompt} marker.\nYour subject text is placed at {prompt} — without it the subject gets appended at the end. Add it?"))) return;
    payload.style_prompt = `${payload.style_prompt.trim().replace(/,+$/, ", ")} {prompt}`;
  }
  const isFirst = !payload.file;
  const r = await api(isFirst ? "/api/styles" : `/api/styles/${encodeURIComponent(payload.file)}`, { json: payload })
    .catch((e) => (toast(esc(e.message), "err"), null));
  if (!r) return;
  editing = null;
  toast(`Style saved: ${esc(payload.name)}`, "ok");
  await onChangedAndList();
  if (isFirst) cbs.onPickStyle?.(payload.name);   // hand a brand-new style to the Generate panel
}

function tryIt() {
  if (!editing) return;
  const name = editing.name;
  close();
  cbs.onPickStyle?.(name);
}

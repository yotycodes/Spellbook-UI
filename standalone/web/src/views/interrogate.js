// standalone/web/src/views/interrogate.js
// Image interrogation, ViT tag analysis, Krita bridge, tag cleaner, and prompt cleaning buttons.

import { $, $$, api, esc, fmt, toast, copyText } from "../api.js";
import { state, ir } from "../state.js";
import { showView, refreshKrita } from "../main.js";
import { fillStyles, select } from "../components/inspector.js";
import { sendToGenerate, setRemixFile } from "./generate.js";
import { renderActiveChips, renderGrid, renderPager, searchToken } from "./library.js";

let ifile = null;

export const GROUP_ICON = {
  Character: "ph-identification-badge",
  Appearance: "ph-t-shirt",
  "Pose & framing": "ph-person-simple-run",
  Expression: "ph-smiley",
  Background: "ph-mountains",
  Other: "ph-dots-three-circle",
};

export const DEFAULT_ON = new Set(["Character", "Appearance"]);

export const IMAGE_MODES = [
  ["reference", "Reference", "ph-image", "Copies subject and look (IP-Adapter)"],
  ["style", "Style", "ph-palette", "Copies only the art style"],
  ["face", "Face", "ph-smiley", "Keeps the face"],
  ["pose", "Pose", "ph-person-simple-run", "Krita extracts the pose skeleton"],
];

export const sdTag = (t) => t.replace(/\(/g, "\\(").replace(/\)/g, "\\)");

const dz = $("#dropzone");
dz?.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
dz?.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz?.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); if (e.dataTransfer.files[0]) pickImage(e.dataTransfer.files[0]); });
$("#ifile")?.addEventListener("change", (e) => e.target.files[0] && pickImage(e.target.files[0]));

$("#ipreset")?.addEventListener("change", () => {
  const local = state.meta?.engines?.find((name) => name === "Local (Ollama)");
  if ($("#ipreset").value.includes("Natural Language") && local && $("#iengine").value === state.meta?.default_engine) {
    $("#iengine").value = local;
    toast("Using Local (Ollama) for natural-language output. You can choose another writing engine.", "info");
  }
});

document.addEventListener("paste", (e) => {
  if (e.target.matches?.("input, textarea")) return;
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith("image/"));
  if (!f) return;
  e.preventDefault();
  showView("interrogate");
  pickImage(f);
  toast("Image pasted", "info");
});

export function pickImage(f) {
  if (!f.type.startsWith("image/")) return toast("That isn't an image file. Drop a PNG, JPG or WebP instead.", "err");
  ifile = f;
  showPreview(URL.createObjectURL(f));
  const runBtn = $("#irun");
  if (runBtn) runBtn.disabled = false;
}

export function showPreview(src) {
  const img = $("#ipreview");
  if (!img) return;
  img.src = src; img.hidden = false;
  const empty = $(".dz-empty");
  if (empty) empty.hidden = true;
}

$("#irun")?.addEventListener("click", async () => {
  if (!ifile) return;
  const btn = $("#irun"); btn.disabled = true; btn.innerHTML = `<i class="ph ph-circle-notch spin"></i>Reading image…`;
  $("#iresult").innerHTML = `<div class="pane">${Array.from({ length: 10 }, (_, i) => `<div class="skel-line" style="width:${90 - (i % 3) * 18}%"></div>`).join("")}</div>`;
  const fd = new FormData(); fd.append("image", ifile); fd.append("preset", $("#ipreset").value); fd.append("engine", $("#iengine").value);
  try {
    showResult(await api("/api/interrogate", { method: "POST", body: fd }));
    renderHistory();
  } catch (e) {
    $("#iresult").innerHTML = `<div class="placeholder"><i class="ph ph-warning-circle"></i><p>${esc(e.message)}</p></div>`;
  }
  btn.disabled = false; btn.innerHTML = `<i class="ph ph-sparkle"></i>Interrogate`;
});

export function showResult(r) {
  ir.res = r;
  ir.thresh = r.thresholds?.general ?? 0.35;
  ir.on = new Set((r.tags || []).filter((t) => DEFAULT_ON.has(t.group) && t.score >= ir.thresh).map((t) => t.tag));
  const legacy = !r.tags;
  $("#iresult").innerHTML = `
    <div class="label-row"><span>Prompt</span><span class="muted">${esc(r.engine)} · ${esc(r.preset || "")}</span><button class="icon-btn" data-clean="#irPrompt" title="Clean tags" aria-label="Clean tags"><i class="ph ph-broom"></i></button><button class="icon-btn" data-copy="#irPrompt" title="Copy" aria-label="Copy"><i class="ph ph-copy"></i></button></div>
    <textarea id="irPrompt" class="ta ta-short">${esc(r.prompt)}</textarea>
    <div style="display:flex;gap:8px;margin-bottom:10px;">
      <button class="btn btn-primary" id="irGen" title="Load the prompt and preset settings into Generate"><i class="ph ph-magic-wand"></i>Open in Generate</button>
      <button class="btn" id="irRemix" title="Load the prompt and this image into Generate as a remix"><i class="ph ph-shuffle-angular"></i>Remix in Generate</button>
    </div>
    <details class="disclosure"><summary>Negative and notes</summary>
      <textarea id="irNeg" class="ta ta-short">${esc(r.negative)}</textarea>
      <ul class="notes">${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    </details>
    ${legacy ? "" : `
    <div class="tags-head">
      <span class="label-strong">Tags</span><span class="muted" id="irCount"></span>
      <label class="thresh" title="Hide tags the tagger is less sure about">Confidence <input type="range" id="irThresh" min="0.2" max="0.9" step="0.05" value="${ir.thresh}"><b id="irThreshV"></b></label>
    </div>
    <div class="tag-groups" id="irGroups"></div>`}
    <div class="krita-box">
      <div class="label-row"><span>Krita prompt</span><span class="muted">${legacy ? "character tags" : "built from the tags you keep"}</span><button class="icon-btn" data-copy="#irChar" title="Copy" aria-label="Copy"><i class="ph ph-copy"></i></button></div>
      <textarea id="irChar" class="ta ta-short">${esc(r.character)}</textarea>
      <div class="send-grid">
        <label class="field grow"><span>Style</span><select id="irStyle"></select></label>
        <div class="field"><span>Send image as</span><div class="seg multi" id="irModes">${IMAGE_MODES.map(([k, l, i, t]) =>
          `<button data-m="${k}" title="${t}" class="${ir.modes.has(k) ? "is-on" : ""}"><i class="ph ${i}"></i>${l}</button>`).join("")}</div></div>
      </div>
      <button class="btn btn-block" id="irKrita"><i class="ph ph-paper-plane-tilt"></i><span id="irKritaL"></span></button>
    </div>
    <div class="similar">
      <div class="label-row"><span>Similar in library</span><span class="muted" id="irSimNote">matching the tags you keep</span><button class="icon-btn" id="irSimRefresh" title="Refresh" aria-label="Refresh"><i class="ph ph-arrows-clockwise"></i></button></div>
      <div class="chips" id="irLoras"></div>
      <div class="sim-grid" id="irSim"></div>
    </div>`;
  fillStyles($("#irStyle"), r.krita_style);
  if (!legacy) {
    renderTagGroups();
    $("#irThresh")?.addEventListener("input", (e) => { ir.thresh = Number(e.target.value); renderTagGroups(); });
    $("#irThresh")?.addEventListener("change", () => loadSimilar());
  }
  updateKritaLabel();
  $("#irModes")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    ir.modes.has(b.dataset.m) ? ir.modes.delete(b.dataset.m) : ir.modes.add(b.dataset.m);
    b.classList.toggle("is-on", ir.modes.has(b.dataset.m));
    updateKritaLabel();
  });
  $("#irKrita").onclick = sendInterrogateToKrita;
  $("#irGen").onclick = () => {
    const st = ir.res.settings || {};
    sendToGenerate({
      prompt: $("#irPrompt").value, negative: $("#irNeg").value, sampler: st.sampler, scheduler: st.scheduler,
      steps: st.steps, cfg: st.cfg, width: st.width, height: st.height, clip_skip: st.clip_skip,
      seed: -1, style: "",
    }, "Interrogate result");
  };
  $("#irRemix").onclick = async () => {
    const st = ir.res?.settings || {};
    sendToGenerate({
      prompt: $("#irPrompt").value, negative: $("#irNeg").value, sampler: st.sampler, scheduler: st.scheduler,
      steps: st.steps, cfg: st.cfg, width: st.width, height: st.height, clip_skip: st.clip_skip, seed: -1, style: "",
    }, "Interrogate result");
    if (ifile) {
      await setRemixFile(ifile);
      $("#gRemixBox").open = true;
      toast("Loaded prompt and image into Remix", "ok");
    }
  };
  $("#irSimRefresh").onclick = () => loadSimilar();
  loadSimilar();
}

export function visibleTags() { return (ir.res?.tags || []).filter((t) => t.group === "Character" || t.score >= ir.thresh); }

export function renderTagGroups() {
  $("#irThreshV").textContent = `${Math.round(ir.thresh * 100)}%`;
  const vis = visibleTags();
  const groups = [...new Set(vis.map((t) => t.group))];
  groups.sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b));
  $("#irGroups").innerHTML = groups.map((g) => {
    const tags = vis.filter((t) => t.group === g);
    const all = tags.every((t) => ir.on.has(t.tag));
    return `<div class="tag-group">
      <button class="tg-head${all ? " is-on" : ""}" data-g="${esc(g)}" title="${all ? "Drop" : "Keep"} every ${esc(g.toLowerCase())} tag">
        <i class="ph ${GROUP_ICON[g] || "ph-tag"}"></i>${esc(g)}<span>${tags.filter((t) => ir.on.has(t.tag)).length}/${tags.length}</span></button>
      <div class="chips">${tags.map((t) => `<button class="chip tagchip${ir.on.has(t.tag) ? " is-on" : ""}" data-t="${esc(t.tag)}">${esc(t.tag)}<small>${Math.round(t.score * 100)}</small></button>`).join("")}</div>
    </div>`;
  }).join("") || `<p class="muted">No tags above ${Math.round(ir.thresh * 100)}%. Lower the confidence.</p>`;
  const kept = vis.filter((t) => ir.on.has(t.tag)).length;
  $("#irCount").textContent = `${kept} of ${vis.length} kept`;
  buildKritaPrompt();
}

$("#iresult")?.addEventListener("click", (e) => {
  const chip = e.target.closest(".tagchip");
  if (chip) { const t = chip.dataset.t; ir.on.has(t) ? ir.on.delete(t) : ir.on.add(t); renderTagGroups(); scheduleSimilar(); return; }
  const head = e.target.closest(".tg-head");
  if (head) {
    const tags = visibleTags().filter((t) => t.group === head.dataset.g);
    const all = tags.every((t) => ir.on.has(t.tag));
    tags.forEach((t) => (all ? ir.on.delete(t.tag) : ir.on.add(t.tag)));
    renderTagGroups(); scheduleSimilar(); return;
  }
  const sim = e.target.closest(".sim-card");
  if (sim) openSimilar(Number(sim.dataset.i));
});

export const GROUP_ORDER = ["Character", "Appearance", "Pose & framing", "Expression", "Background", "Other"];

export function keptTags() {
  return visibleTags().filter((t) => ir.on.has(t.tag))
    .sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group) || b.score - a.score);
}

export function buildKritaPrompt() {
  const charEl = $("#irChar");
  if (charEl) charEl.value = keptTags().map((t) => sdTag(t.tag)).join(", ");
}

export function updateKritaLabel() {
  const n = ir.modes.size;
  const lbl = $("#irKritaL");
  if (lbl) {
    lbl.textContent = n ? `Send prompt + image (${[...ir.modes].map((m) => IMAGE_MODES.find((x) => x[0] === m)[1].toLowerCase()).join(", ")}) to Krita` : "Send prompt to Krita";
  }
}

export async function sendInterrogateToKrita() {
  const btn = $("#irKrita"); btn.disabled = true;
  try {
    const res = await api("/api/krita/prompt", { json: { prompt: $("#irChar").value, negative: "", style: $("#irStyle").value } });
    if (!res.ok) { toast(esc(res.error), "err"); return; }
    if (ir.modes.size && ir.res?.id) {
      const im = await api("/api/krita/image", { json: { id: ir.res.id, modes: [...ir.modes] } });
      if (!im.ok) { toast(`Prompt sent, image wasn't: ${esc(im.error)}`, "err"); return; }
      toast(`Sent to Krita, style ${esc(res.style)}, image as ${esc(im.modes.join(", ") || "layer")}${im.note ? `. ${esc(im.note)}` : ""}`);
    } else toast(`Sent to Krita, style ${esc(res.style)}`);
  } catch (e) { toast(esc(e.message), "err"); }
  finally { btn.disabled = false; refreshKrita(); }
}

let simTimer, simToken = 0;
export const scheduleSimilar = () => { clearTimeout(simTimer); simTimer = setTimeout(loadSimilar, 450); };

export async function loadSimilar() {
  if (!ir.res) return;
  const token = ++simToken;
  const tags = ir.res.tags ? keptTags() : (ir.res.character || "").split(",").map((t) => ({ tag: t.trim().replace(/\\/g, ""), score: 0.6, group: "Appearance" })).filter((t) => t.tag);
  $("#irSim").innerHTML = Array.from({ length: 8 }, () => `<div class="sim-card skel"></div>`).join("");
  try {
    const r = await api("/api/similar", { json: { tags, rating: state.rating === "SFW" ? "SFW" : "All", limit: 16 } });
    if (token !== simToken) return;
    ir.similar = r.items;
    $("#irLoras").innerHTML = r.loras.length
      ? `<span class="muted lora-label"><i class="ph ph-puzzle-piece"></i>Your LoRAs that match</span>` + r.loras.map((l) => `<span class="chip static" title="Installed LoRA">${esc(l)}</span>`).join("")
      : "";
    $("#irSim").innerHTML = r.items.length ? r.items.map((it, i) => `
      <button class="sim-card" data-i="${i}" title="#${it.id} · open in library"><img loading="lazy" src="/api/thumb/${it.id}" alt=""><span><i class="ph-fill ph-heart"></i>${fmt(it.react)}</span></button>`).join("")
      : `<p class="muted">No library prompts share these tags.</p>`;
    $$("#irSim img").forEach((img) => img.addEventListener("error", () => img.remove()));
  } catch (e) { if (token === simToken) $("#irSim").innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

export function openSimilar(i) {
  if (!ir.similar?.length) return;
  state.similar = true;
  state.items = ir.similar.map((x) => ({ ...x, fav: false }));
  state.total = ir.similar.length;
  state.page = 0;
  state.pages = 1;
  state.sel = -1;
  showView("library");
  renderActiveChips(); renderGrid(); renderPager();
  $("#pagerCount").innerHTML = `<b>${ir.similar.length}</b> prompts similar to your image`;
  select(i);
}

export async function renderHistory() {
  try {
    const items = await api("/api/interrogate/history");
    $("#ihistory").innerHTML = items.length ? items.slice(0, 24).map((h) => `
      <div class="hist${ir.res?.id === h.id ? " is-on" : ""}" data-id="${h.id}" role="button" tabindex="0" title="${esc(h.preset)} · ${esc(h.engine)}">
        <img loading="lazy" src="/api/interrogate/image/${h.id}" alt=""><button class="hist-x" data-del="${h.id}" title="Remove"><i class="ph ph-x"></i></button></div>`).join("")
      : `<p class="muted">Images you interrogate show up here.</p>`;
  } catch { /* history is optional */ }
}

$("#ihistory")?.addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); await api("/api/interrogate/delete", { json: { id: del.dataset.del } }); renderHistory(); return; }
  const h = e.target.closest(".hist"); if (!h) return;
  try {
    const r = await api(`/api/interrogate/result/${h.dataset.id}`);
    showPreview(`/api/interrogate/image/${r.id}`);
    const blob = await fetch(`/api/interrogate/image/${r.id}`).then((x) => x.blob());
    ifile = new File([blob], `${r.id}.jpg`, { type: "image/jpeg" });
    $("#irun").disabled = false;
    showResult(r);
    $$("#ihistory .hist").forEach((x) => x.classList.toggle("is-on", x === h));
  } catch (err) { toast(esc(err.message), "err"); }
});

$$("#ckind button").forEach((b) => b.addEventListener("click", () => $$("#ckind button").forEach((x) => x.classList.toggle("is-on", x === b))));
$("#cframe")?.addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on)); e.currentTarget.classList.toggle("is-on", on);
});
$("#crun")?.addEventListener("click", async () => {
  const r = await api("/api/clean", {
    json: {
      text: $("#cin").value, negative: $("#ckind .is-on")?.dataset.v === "neg",
      framing: $("#cframe")?.getAttribute("aria-pressed") === "true",
    },
  });
  $("#cout").value = r.text;
  $("#cnotes").innerHTML = r.notes.length ? r.notes.map((n) => `<li>${esc(n)}</li>`).join("") : `<li>Already clean, nothing changed.</li>`;
});

export async function cleanPromptElement(el, isNeg = false) {
  if (!el) return;
  const raw = el.value ?? el.textContent ?? "";
  if (!raw.trim()) return toast("Nothing to clean", "info");
  try {
    const r = await api("/api/clean", { json: { text: raw, negative: isNeg, framing: true } });
    if (r.text != null) {
      if (el.value !== undefined) el.value = r.text;
      else el.textContent = r.text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      const count = (r.notes || []).length;
      toast(count ? `Cleaned prompt (${count} improvement${count === 1 ? "" : "s"})` : "Prompt already clean", "ok");
    }
  } catch (err) {
    toast(`Clean failed: ${err.message}`, "err");
  }
}

document.addEventListener("click", (e) => {
  const csel = e.target.closest("[data-clean]")?.dataset.clean;
  if (csel) cleanPromptElement($(csel));
  const sel_ = e.target.closest("[data-copy]")?.dataset.copy;
  if (sel_) copyText($(sel_)?.value || "");
});

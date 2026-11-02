// standalone/web/src/components/inspector.js
// Inspector panel: record details, Krita send, pose swap, collections, more-like-this.

import { $, $$, api, esc, fmt, label, toast } from "../api.js";
import { state, savePrefs, pushState, gen } from "../state.js";
import { showView, refreshKrita } from "../main.js";
import { packBrowser } from "./pose-browser.js";
import { zoom } from "./lightbox.js";
import { fillSelect, newSearch, renderActiveChips, renderGrid, renderPager } from "../views/library.js";
import { openInGenerate, genParams, startPolling } from "../views/generate.js";

export const recCache = new Map();

export function getRecord(id) {
  if (!recCache.has(id)) {
    const p = api(`/api/record/${id}`);
    recCache.set(id, p);
    p.catch(() => recCache.delete(id));
    if (recCache.size > 400) recCache.delete(recCache.keys().next().value);
  }
  return recCache.get(id);
}

export async function select(i) {
  if (i < 0 || i >= state.items.length) return;
  state.sel = i;
  state.inspect = i;
  pushState(true);
  $$(".card").forEach((c) => c.classList.toggle("is-selected", Number(c.dataset.i) === i));
  $(`.card[data-i="${i}"]`)?.scrollIntoView({ block: "nearest", behavior: "auto" });
  const id = state.items[i].id;
  $("#app").classList.add("inspecting");
  $("#inspector").inert = false;

  $("#iThumb").src = `/api/thumb/${id}`;
  $("#iId").textContent = id;
  try {
    const r = await getRecord(id);
    if (state.items[state.sel]?.id !== id) return;
    state.record = r;
    fillInspector(r);
    [i + 1, i - 1].forEach((j) => state.items[j] && getRecord(state.items[j].id).catch(() => {}));
  } catch (e) {
    toast(`Couldn't load #${id} (${esc(e.message)}). Pick it again to retry, or reopen the app if it keeps failing.`, "err");
  }
}

export function closeInspector() {
  $("#app").classList.remove("inspecting");
  $("#inspector").inert = true;
  state.inspect = null;
  pushState(true);
}

$("#iClose")?.addEventListener("click", closeInspector);

export function fillStyles(el, suggested) {
  const all = state.meta?.krita_styles || [];
  const rest = all.filter((n) => n !== suggested);
  el.innerHTML = (suggested ? `<option value="${esc(suggested)}">${esc(suggested)} (suggested)</option>` : "")
    + rest.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  el.value = suggested || rest[0] || "";
}

export function fillInspector(r) {
  loadMoreLike(r);
  loadSuggest(r.id);
  $("#iBase").textContent = r.base;
  $("#iReact").textContent = fmt(r.react);
  const run = $("#iRun");
  run.className = `badge ${r.runnable ? "ok" : "warn"}`;
  run.title = r.runnable ? "Uses an Illustrious-family model and only LoRAs you have" : "Uses a model or LoRA you don't have installed";
  run.innerHTML = r.runnable ? `<i class="ph ph-check-circle"></i>Runnable` : `<i class="ph ph-warning"></i>Missing models`;
  if (r.source === "interrogated") {
    run.className = "badge info";
    run.title = "The creator hid this prompt, so it was rebuilt from the image with the tagger. Settings are Forge defaults.";
    run.innerHTML = `<i class="ph ph-scan"></i>Prompt from tagger`;
  }
  $("#iSave").classList.toggle("is-on", r.collections.length > 0);
  $("#iSave i").className = r.collections.length ? "ph-fill ph-bookmark-simple" : "ph ph-bookmark-simple";
  // Krita
  fillStyles($("#kStyle"), r.krita.style);
  $("#kCanvas").textContent = r.krita.canvas;
  $("#kPrompt").value = r.krita.prompt;
  $("#kNeg").value = r.krita.negative;
  $("#kNotes").innerHTML = r.krita.notes.map((n) => `<li>${esc(n)}</li>`).join("");
  // Pose
  $("#pTags").value = r.pose_tags.join(", ");
  state.poseKey = null;
  renderPoses();
  // Original
  $("#oPrompt").value = r.prompt;
  $("#oNeg").value = r.negative;
  $("#oTags").innerHTML = r.tags.map((t) => `<button class="chip" data-tag="${esc(t)}">${esc(t)}</button>`).join("");
  // Details
  const s = r.settings;
  const specs = [
    ["Sampler", s.sampler], ["Schedule", s.scheduler || "Automatic"], ["Steps", s.steps],
    [s.distilled_cfg ? "Distilled CFG" : "CFG", s.distilled_cfg ?? s.cfg], ["Size", `${s.width} × ${s.height}`],
    ["Clip skip", s.clip_skip || "None"], ["Rating", r.nsfw], ["Themes", (r.themes || []).join(", ") || "None"],
  ];
  $("#dSpecs").innerHTML = specs.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v ?? "None")}</dd></div>`).join("");
  $("#dLoras").innerHTML = r.loras.length
    ? r.loras.map((l) => `<li><i class="ph-fill ${l.installed ? "ph-check-circle ok" : "ph-warning-circle warn"}"></i><b>${esc(l.name)}</b><span>${l.weight ?? ""}</span></li>`).join("")
    : `<li><i class="ph ph-minus-circle"></i><b>No LoRAs</b></li>`;
  $("#dColList").innerHTML = (state.meta?.collections || []).map((c) => `<option value="${esc(c)}">`).join("");
  $("#dCol").value = r.collections[0] || state.meta?.collections[0] || "";
  $("#dNote").value = r.note || "";
  renderIn(r.collections);
}

export function renderIn(cols) {
  $("#dIn").innerHTML = cols.length
    ? cols.map((c) => `<span class="chip static"><i class="ph-fill ph-bookmark-simple"></i>${esc(label(c))}<button data-rm="${esc(c)}" title="Remove from ${esc(c)}"><i class="ph ph-x"></i></button></span>`).join("")
    : `<span class="muted">Not in any collection yet.</span>`;
}

$$(".tab").forEach((t) => t.addEventListener("click", () => {
  state.tab = t.dataset.tab; savePrefs();
  $$(".tab").forEach((x) => x.classList.toggle("is-on", x === t));
  $$(".tabpane").forEach((p) => p.classList.toggle("is-on", p.dataset.pane === t.dataset.tab));
}));

$("#oTags")?.addEventListener("click", (e) => {
  const t = e.target.closest("[data-tag]")?.dataset.tag;
  if (!t) return;
  state.q = t; $("#q").value = t; newSearch();
  toast(`Showing prompts with “${esc(t)}”`, "info");
});

$("#iOpen")?.addEventListener("click", () => {
  const url = state.record?.url;
  if (!url) { toast("This prompt came from a local file — nothing to open online.", "info"); return; }
  api("/api/open", { json: { url } }).catch((e) => toast(esc(e.message), "err"));
});

export async function sendToKrita() {
  if (!state.record) return;
  const btn = $("#kSend"); btn.disabled = true;
  try {
    const r = await api("/api/krita/prompt", { json: { prompt: $("#kPrompt").value, negative: $("#kNeg").value, style: $("#kStyle").value } });
    r.ok ? toast(`Sent to Krita, style ${esc(r.style)}${r.note ? `. ${esc(r.note)}` : ""}`) : toast(esc(r.error), "err");
  } catch (e) { toast(esc(e.message), "err"); }
  btn.disabled = false;
  refreshKrita();
}

$("#kSend")?.addEventListener("click", sendToKrita);

export function renderPoses() {
  $("#pSkel").disabled = !state.packPose;
}

$("#pSwap")?.addEventListener("click", async () => {
  if (!state.record) return;
  const r = await api("/api/pose/swap", { json: { prompt: $("#kPrompt").value, pose: $("#pTags").value } });
  $("#kPrompt").value = r.prompt;
  toast("Pose swapped into the Krita prompt");
});

$("#pSkel")?.addEventListener("click", async () => {
  if (!state.packPose) return;
  try {
    const r = await api("/api/krita/pose", { json: { pack_id: state.packPose.id } });
    r.ok ? toast(`Added ${esc(r.layer)} as a Pose control in Krita${r.note ? `. ${esc(r.note)}` : ""}`) : toast(esc(r.error), "err");
  } catch (e) { toast(esc(e.message), "err"); }
});

state.packPose = null;

export function pickInspectorPose(x) {
  state.packPose = x; state.poseKey = null;
  $("#pSkel").disabled = !x;
  if (x) { $("#pTags").value = x.ptags || ""; }
  pBrowser.draw(); drawSuggest();
}

export const pBrowser = packBrowser($("#pPacks"), pickInspectorPose, () => state.packPose?.id);

let suggestItems = [];

export async function loadSuggest(rid) {
  $("#pSuggest").innerHTML = Array.from({ length: 4 }, () => `<div class="sim-card skel"></div>`).join("");
  const r = await api(`/api/posepacks/suggest/${rid}?rating=${state.poseRating}`).catch(() => ({ items: [], wanted: [] }));
  if (state.record?.id !== rid) return;
  suggestItems = r.items;
  $("#pSuggestNote").textContent = r.wanted.length ? `${r.used.join(" + ") || "no exact match"}` : "no pose words in this prompt";
  drawSuggest();
}

export function drawSuggest() {
  const sel = state.packPose?.id;
  $("#pSuggest").innerHTML = suggestItems.length ? suggestItems.map((x) => `<button class="pack-pose${x.id === sel ? " is-on" : ""}" data-id="${x.id}" title="${esc(x.tags.join(", "))}"><img loading="lazy" src="/api/posepacks/thumb/${x.id}" alt=""></button>`).join("")
    : `<p class="muted">Pick from all poses below.</p>`;
}

$("#pSuggest")?.addEventListener("click", (e) => {
  const p = e.target.closest(".pack-pose"); if (!p) return;
  const x = suggestItems.find((i) => i.id === p.dataset.id);
  pickInspectorPose(state.packPose?.id === x.id ? null : x);
  if (state.packPose) api("/api/posepacks/used", { json: { id: x.id } }).catch(() => {});
});

$$(".tab").forEach((t) => t.addEventListener("click", () => {
  if (t.dataset.tab === "pose" && !pBrowser.loaded) {
    pBrowser.loaded = true;
    pBrowser.load();
  }
}));

export async function saveFav(collection, note) {
  if (!state.record) { toast("No prompt selected", "info"); return; }
  const coll = (collection || state.record?.collections?.[0] || state.meta?.collections?.[0]);
  if (!coll) { toast("No collection available", "info"); return; }
  try {
    const payload = { id: state.record.id, collection: coll };
    if (note !== undefined && note !== null) payload.note = note;
    const r = await api("/api/favorites", { json: payload });
    // Refresh full meta from server so collections list and fav flags stay in sync
    try {
      const meta = await api("/api/meta");
      state.meta = meta;
      if (state.record) state.record.collections = meta.collections;
    } catch {}
    state.items[state.sel] && (state.items[state.sel].fav = true);
    renderIn(r.in);
    if ($("#f-collection")) fillSelect($("#f-collection"), ["All", ...(state.meta?.collections || [])], state.collection);
    $("#iSave").classList.add("is-on"); $("#iSave i").className = "ph-fill ph-bookmark-simple";
    const card = $(`.card[data-i="${state.sel}"]`);
    if (card && !$(".card-fav", card)) card.insertAdjacentHTML("beforeend", `<span class="card-fav"><i class="ph-fill ph-bookmark-simple"></i></span>`);
    toast(`Saved to ${esc(r.collection)}`);
  } catch (e) {
    toast(`Save failed: ${esc(e.message)}`, "err");
  }
}

// Event delegation for iSave to survive DOM timing issues
function attachInspectorHandlers() {
  const inspectorEl = $("#inspector");
  if (!inspectorEl) return;
  // Remove existing to avoid duplicates
  inspectorEl.removeEventListener("click", inspectorEl._iSaveHandler);
  inspectorEl._iSaveHandler = async (e) => {
    const btn = e.target.closest("#iSave");
    if (!btn) return;
    if (!state.record) { toast("Open a prompt first", "info"); return; }
    const coll = state.record?.collections?.[0] || state.meta?.collections?.[0];
    if (!coll) { toast("No collection available", "info"); return; }
    // Toggle: remove from the collection the library is filtered to when it
    // applies; otherwise the prompt's first membership.
    if (state.record.collections.length > 0) {
      const removeColl = state.record.collections.includes(state.collection) ? state.collection : state.record.collections[0];
      try {
        const r = await api("/api/favorites/remove", { json: { id: state.record.id, collection: removeColl } });
        try { state.meta = await api("/api/meta"); } catch {}
        state.record.collections = r.in;
        renderIn(r.in);
        $("#iSave").classList.remove("is-on");
        $("#iSave i").className = "ph ph-bookmark-simple";
        state.items[state.sel] && (state.items[state.sel].fav = false);
        const card = $(`.card[data-i="${state.sel}"]`);
        card?.querySelector(".card-fav")?.remove();
        toast(`Removed from ${esc(label(removeColl))}`, "info");
      } catch (e) {
        toast(`Remove failed: ${esc(e.message)}`, "err");
      }
    } else {
      saveFav(coll, undefined);
    }
  };
  inspectorEl.addEventListener("click", inspectorEl._iSaveHandler);
}
attachInspectorHandlers();
document.addEventListener("DOMContentLoaded", attachInspectorHandlers);

// Re-attach handlers after DOM load to ensure elements exist
document.addEventListener("DOMContentLoaded", () => {
  $("#dSave")?.addEventListener("click", () => saveFav($("#dCol").value.trim() || state.meta?.collections?.[0], $("#dNote").value));
});
$("#dIn")?.addEventListener("click", async (e) => {
  const c = e.target.closest("[data-rm]")?.dataset.rm;
  if (!c || !state.record) return;
  const r = await api("/api/favorites/remove", { json: { id: state.record.id, collection: c } });
  try { state.meta = await api("/api/meta"); } catch {}
  state.record.collections = r.in;
  renderIn(r.in);
  if (!r.in.length) { $("#iSave").classList.remove("is-on"); $("#iSave i").className = "ph ph-bookmark-simple"; }
  toast(`Removed from ${esc(label(c))}`, "info");
});

export async function loadMoreLike(r) {
  $("#oSim").innerHTML = Array.from({ length: 4 }, () => `<div class="sim-card skel"></div>`).join("");
  const tags = (r.tags || []).slice(0, 24).map((t, i) => ({
    tag: t.replace(/\\/g, "").replace(/^\(|:[\d.]+\)$/g, ""),
    score: 1 - i * 0.02,
    group: r.hero && t.toLowerCase().includes(r.hero) ? "Character" : "Appearance",
  }));
  const res = await api("/api/similar", { json: { tags, rating: state.rating === "SFW" ? "SFW" : "All", limit: 9 } }).catch(() => ({ items: [] }));
  if (state.record?.id !== r.id) return;
  const items = res.items.filter((x) => x.id !== r.id).slice(0, 8);
  gen.moreLike = items;
  $("#oSim").innerHTML = items.length ? items.map((it, i) => `<button class="sim-card" data-ml="${i}" title="#${it.id}"><img loading="lazy" src="/api/thumb/${it.id}" alt=""><span><i class="ph-fill ph-heart"></i>${fmt(it.react)}</span></button>`).join("")
    : `<p class="muted">Nothing close enough.</p>`;
}

$("#oSim")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-ml]"); if (!b) return;
  showItemList(gen.moreLike, Number(b.dataset.ml), `prompts like #${state.record.id}`);
});

export function showItemList(items, i, what) {
  state.similar = true;
  state.items = items.map((x) => ({ ...x, fav: false }));
  state.total = items.length;
  state.page = 0;
  state.pages = 1;
  state.sel = -1;
  showView("library");
  renderActiveChips(); renderGrid(); renderPager();
  $("#pagerCount").innerHTML = `<b>${items.length}</b> ${esc(what)}`;
  $("#charCard").hidden = true;
  select(i);
}

$("#iThumb")?.addEventListener("click", () => {
  if (!state.record) return;
  $("#lightbox").classList.add("viewer");
  zoom.reset();
  $("#lbImg").src = $("#iThumb").src;
  const big = new Image(); const id = state.record.id;
  big.onload = () => { if (!$("#lightbox").hidden && state.record?.id === id) $("#lbImg").src = big.src; };
  big.src = `/api/large/${id}`;
  $("#lbMeta").innerHTML = `<b>#${esc(state.record.id)}</b> · ${esc(state.record.base)} · ${fmt(state.record.react)} reactions`;
  $("#lightbox").hidden = false;
});

$("#oGen")?.addEventListener("click", () => state.record && openInGenerate(state.record.id));
$("#kGen")?.addEventListener("click", () => state.record && openInGenerate(state.record.id, { prompt: $("#kPrompt").value, style: $("#kStyle").value, styleFill: true, ...($("#kNeg").value.trim() ? { negative: $("#kNeg").value } : { negative: "" }) }));
$("#kQuickRender")?.addEventListener("click", async () => {
  if (!gen.opts?.online) return toast("Start Forge first to render", "info");
  if (!state.record) return;
  const prompt = $("#kPrompt").value.trim() || state.record.prompt;
  const style = $("#kStyle").value || "";
  const negative = $("#kNeg").value.trim() || "";
  const base = genParams();
  const job = {
    params: {
      ...base,
      mode: "txt2img",
      prompt,
      negative: style ? base.negative : negative,
      style,
      seed: -1,
      count: 1,
    },
    label: `#${state.record.id} · ${prompt.slice(0, 45)}`,
  };
  try {
    await api("/api/gen/run", { json: { jobs: [job] } });
    toast(`Queued test render for #${state.record.id}`);
    startPolling();
  } catch (e) {
    toast(esc(e.message), "err");
  }
});

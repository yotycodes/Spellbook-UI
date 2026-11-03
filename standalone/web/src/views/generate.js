// standalone/web/src/views/generate.js
// Generation workbench: model/sampler tuning, pose controls, hires/ADetailer enhancement,
// batch queues, drag-and-drop reordering, comparison matrices, and generation gallery.

import { $, $$, api, esc, fmt, toast, copyText, confirmDialog } from "../api.js";
import { state, gen, forge, PREFS_GEN, NATIVE } from "../state.js";
import { showView } from "../main.js";
import { packBrowser, poseClass, modalBrowser } from "../components/pose-browser.js";
import { openLightbox, renderLbStrip, askFixes, queueFixes, galLabel } from "../components/lightbox.js";
import { fillSelect } from "./library.js";
import { pickImage } from "./interrogate.js";
import { openStyles } from "../components/styles-manager.js";

export function switchGenSubTab(name) {
  gen.activeSubTab = name;
  saveGen();
  $$("#genSubTabs .gen-subtab").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-selected", String(on));
  });
  $$(".gen-subpane").forEach((p) => {
    p.classList.toggle("is-on", p.dataset.pane === name);
  });
  if (name === "poses") {
    if (typeof gBrowser !== "undefined" && !gBrowser.loaded) {
      gBrowser.loaded = true;
      gBrowser.load();
    }
  }
}

$("#genSubTabs")?.addEventListener("click", (e) => {
  const b = e.target.closest(".gen-subtab");
  if (b) switchGenSubTab(b.dataset.tab);
});

export function updateSubTabIndicators() {
  const indPoses = $("#indPoses");
  if (indPoses) {
    const hasPose = !!(gen.posePack || gen.poseKey);
    const hasRemix = !!gen.remix;
    indPoses.hidden = !(hasPose || hasRemix);
  }
  const indEnhance = $("#indEnhance");
  if (indEnhance) {
    const hiresOn = $("#gHires")?.getAttribute("aria-pressed") === "true";
    const bodyOn = $("#gFixBody")?.getAttribute("aria-pressed") === "true";
    const faceOn = $("#gFixFace")?.getAttribute("aria-pressed") === "true";
    const handsOn = $("#gFixHands")?.getAttribute("aria-pressed") === "true";
    indEnhance.hidden = !(hiresOn || bodyOn || faceOn || handsOn);
  }
  const indBatch = $("#indBatch");
  if (indBatch) {
    const cmpCount = $$("#gCmp input:checked").length;
    const wild = $("#gPrompt")?.value?.includes("{");
    indBatch.hidden = !(cmpCount > 0 || wild);
  }
}

["gPoseBox", "gHiresBox", "gRemixBox", "gBatchBox"].forEach((id) => {
  const el = $(`#${id}`);
  if (el) {
    try {
      Object.defineProperty(el, "open", {
        get() { return el.closest(".gen-subpane")?.classList.contains("is-on") ?? true; },
        set(val) {
          if (val) {
            const pane = el.closest(".gen-subpane")?.dataset.pane;
            if (pane) switchGenSubTab(pane);
          }
        },
        configurable: true,
      });
    } catch {}
  }
});

export function linkSlider(range, num, fmtFn = (v) => v) {
  const r = $(range), n = $(num);
  if (!r || !n) return;
  r.addEventListener("input", () => { n.value = fmtFn(r.value); saveGen(); });
  n.addEventListener("change", () => { r.value = n.value; saveGen(); });
}

linkSlider("#gSteps", "#gStepsN");
linkSlider("#gCfg", "#gCfgN");
linkSlider("#gHrScale", "#gHrScaleN");
["#gHrScale", "#gHrScaleN"].forEach((id) => $(id)?.addEventListener("input", () => setHires($("#gHires")?.getAttribute("aria-pressed") === "true")));
linkSlider("#gHrDen", "#gHrDenN");
linkSlider("#gHrSteps", "#gHrStepsN");

export const setNum = (base, v) => { $(`${base}`).value = v; $(`${base}N`).value = v; };
export const numOf = (base) => Number($(`${base}N`)?.value || $(base)?.value || 0);

export function genParams() {
  return {
    backend: "forge", project: $("#gProject")?.value.trim() || "", style: $("#gStyle")?.value || "", prompt: $("#gPrompt")?.value.trim() || "", negative: $("#gNeg")?.value.trim() || "", model: $("#gModel")?.value || "",
    sampler: $("#gSampler")?.value || "", scheduler: $("#gScheduler")?.value || "",
    steps: numOf("#gSteps"), cfg: numOf("#gCfg"),
    width: Number($("#gW")?.value || 832), height: Number($("#gH")?.value || 1216),
    seed: $("#gSeed")?.value === "" ? -1 : Number($("#gSeed")?.value), count: Number($("#gCount")?.value || 1),
    clip_skip: gen.clipSkip || 0, distilled_cfg: gen.distilled ?? null,
    fix_face: $("#gFixFace")?.getAttribute("aria-pressed") === "true", fix_hands: $("#gFixHands")?.getAttribute("aria-pressed") === "true", fix_body: $("#gFixBody")?.getAttribute("aria-pressed") === "true",
    pose_key: gen.poseKey || null, pose_pack_id: gen.posePack?.id || null, pose_weight: numOf("#gPoseW"),
    pose_depth: $("#gPoseDepth")?.getAttribute("aria-pressed") === "true", pose_depth_set: !!gen.depthSet, pose_depth_weight: numOf("#gDepthW"),
    pose_facing_filter: $("#gPoseFacing")?.getAttribute("aria-pressed") === "true",
    pose_mode: segVal("#gPoseMode") || "auto", pose_check: Number(segVal("#gPoseMin") ?? 0) >= 0, pose_min: Math.max(0, Number(segVal("#gPoseMin") ?? 0)),
    ...(gen.remix ? { mode: "img2img", source: gen.remix.name, denoise: numOf("#gDen"), width: gen.remix.width, height: gen.remix.height } : {}),
    hires: $("#gHires")?.getAttribute("aria-pressed") === "true", hr_upscaler: $("#gHrUp")?.value || "",
    hr_scale: numOf("#gHrScale"), hr_denoise: numOf("#gHrDen"), hr_steps: numOf("#gHrSteps"),
    active_subtab: gen.activeSubTab || "tune",
  };
}

export function saveGen() {
  try {
    localStorage.setItem(PREFS_GEN, JSON.stringify(genParams()));
    localStorage.setItem("pl-pose-added", JSON.stringify(gen.poseAdded || []));
  } catch {}
}

export function applyParams(p) {
  if (p.active_subtab) switchGenSubTab(p.active_subtab);
  if (p.prompt != null) $("#gPrompt").value = p.prompt;
  if (p.project !== undefined) $("#gProject").value = p.project || "";
  if (p.negative != null) $("#gNeg").value = p.negative;
  if (p.model && [...$("#gModel").options].some((o) => o.value === p.model)) $("#gModel").value = p.model;
  if (p.sampler && [...$("#gSampler").options].some((o) => o.value === p.sampler)) $("#gSampler").value = p.sampler;
  if (p.scheduler && [...$("#gScheduler").options].some((o) => o.value === p.scheduler)) $("#gScheduler").value = p.scheduler;
  if (p.steps) setNum("#gSteps", p.steps);
  if (p.cfg) setNum("#gCfg", p.cfg);
  if (p.width) $("#gW").value = p.width;
  if (p.height) $("#gH").value = p.height;
  if (p.seed !== undefined) $("#gSeed").value = p.seed === -1 || p.seed == null ? "" : p.seed;
  if (p.count) $("#gCount").value = p.count;
  if (p.hires !== undefined) setHires(!!p.hires);
  if (p.hr_upscaler && [...$("#gHrUp").options].some((o) => o.value === p.hr_upscaler)) $("#gHrUp").value = p.hr_upscaler;
  if (p.hr_scale) setNum("#gHrScale", p.hr_scale);
  if (p.hr_denoise) setNum("#gHrDen", p.hr_denoise);
  if (p.hr_steps != null) setNum("#gHrSteps", p.hr_steps);
  if (p.fix_face !== undefined) setToggle("#gFixFace", !!p.fix_face);
  if (p.fix_hands !== undefined) setToggle("#gFixHands", !!p.fix_hands);
  if (p.fix_body !== undefined) setToggle("#gFixBody", !!p.fix_body);
  if (p.pose_weight) setNum("#gPoseW", p.pose_weight);
  if (p.pose_mode) setSeg("#gPoseMode", p.pose_mode);
  if (p.pose_facing_filter !== undefined) setToggle("#gPoseFacing", !!p.pose_facing_filter);
  if (p.pose_depth !== undefined && p.pose_depth_set) setToggle("#gPoseDepth", !!p.pose_depth);
  if (p.pose_depth_set) gen.depthSet = true;
  if (p.pose_depth_weight) setNum("#gDepthW", p.pose_depth_weight);
  if (p.pose_check !== undefined) setSeg("#gPoseMin", p.pose_check ? String(p.pose_min || 0) : "-1");
  if (p.pose_key !== undefined) { gen.poseKey = p.pose_key; renderGenPoses(); }
  if (p.pose_pack_id && gen.posePack?.id !== p.pose_pack_id) {
    api(`/api/posepacks/item/${encodeURIComponent(p.pose_pack_id)}`).then((x) => {
      gen.posePack = x; gen.poseKey = null;
      $("#gPoseState").textContent = `${x.tags.slice(0, 3).join(", ") || x.pack.slice(0, 28)}`;
      depthAvail(); if (typeof gBrowser !== "undefined" && gBrowser.loaded) gBrowser.draw();
    }).catch(() => {});
  }
  gen.clipSkip = p.clip_skip || 0; gen.distilled = p.distilled_cfg ?? null;
  if (p.style !== undefined && gen.opts?.styles) setStyle(p.style, !!p.styleFill);
  syncSize(); renderLoraChips(); syncBackendUi(); saveGen(); updateBatchState();
}

export function setStyle(name, fill = true) {
  name = gen.opts?.renamed?.[name] || name;
  const st = (gen.opts?.styles || []).find((x) => x.name === name);
  $("#gStyle").value = st ? name : "";
  $("#gStyleBox").hidden = !st;
  if (!st) { $("#gStyleMeta").textContent = "Manual: you set the checkpoint, LoRAs and settings below."; saveGen(); return; }
  if (fill) {
    if (st.model) $("#gModel").value = st.model;
    if ([...$("#gSampler").options].some((o) => o.value === st.sampler)) $("#gSampler").value = st.sampler;
    if ([...$("#gScheduler").options].some((o) => o.value === st.scheduler)) $("#gScheduler").value = st.scheduler;
    setNum("#gSteps", st.steps); setNum("#gCfg", st.cfg); gen.clipSkip = st.clip_skip;
  }
  const loras = st.loras.map(([n, w]) => `${n} ${w}`).join(", ");
  $("#gStyleMeta").innerHTML = `${esc(st.checkpoint.replace(/\.safetensors$/, ""))} · ${st.loras.length ? esc(loras) : "no LoRAs"} · ${esc(st.sampler)}, ${st.steps} steps, CFG ${st.cfg}`
    + (st.missing.length ? `<br><span class="warn">Missing in Forge: ${esc(st.missing.join(", "))}</span>` : "");
  $("#gStylePrompt").textContent = st.style_prompt;
  $("#gStyleNeg").textContent = st.negative || "none";
  checkStyleOverride();
  saveGen();
}

export function checkStyleOverride() {
  const name = $("#gStyle")?.value;
  const badge = $("#gStyleOverride");
  if (!badge) return;
  if (!name) { badge.hidden = true; return; }
  const st = (gen.opts?.styles || []).find((x) => x.name === name);
  if (!st) { badge.hidden = true; return; }
  const mod = (st.model && $("#gModel").value && $("#gModel").value !== st.model) ||
              (st.sampler && $("#gSampler").value && $("#gSampler").value !== st.sampler) ||
              (st.scheduler && $("#gScheduler").value && $("#gScheduler").value !== st.scheduler) ||
              (st.steps && numOf("#gSteps") !== Number(st.steps)) ||
              (st.cfg && numOf("#gCfg") !== Number(st.cfg));
  badge.hidden = !mod;
}

$("#gStyleRevert")?.addEventListener("click", (e) => {
  e.preventDefault();
  const name = $("#gStyle")?.value;
  if (name) {
    setStyle(name, true);
    toast(`Reset to style defaults (${esc(name)})`, "ok");
  }
});

["#gModel", "#gSampler", "#gScheduler", "#gSteps", "#gStepsN", "#gCfg", "#gCfgN"].forEach((sel) => $(sel)?.addEventListener("change", checkStyleOverride));
["#gSteps", "#gCfg"].forEach((sel) => $(sel)?.addEventListener("input", checkStyleOverride));
$("#gStyle")?.addEventListener("change", (e) => { setStyle(e.target.value); if (e.target.value) toast(`Style: ${esc(e.target.value)}`, "info"); });
$("#gStyleManage")?.addEventListener("click", () => openStyles({
  onChanged: () => { if (gen.opts?.online) loadGenOptions(); },
  onPickStyle: async (name) => { if (!gen.opts?.styles?.length) await loadGenOptions(); setStyle(name, true); if (name) toast(`Style: ${esc(name)}`, "info"); },
}));

$("#gModel")?.addEventListener("change", async (e) => {
  if ($("#gStyle").value) return;
  const model = e.target.value;
  const r = await api(`/api/gen/model-settings?model=${encodeURIComponent(model)}`).catch(() => null);
  if (!r || $("#gModel").value !== model || $("#gStyle").value) return;
  const before = { sampler: $("#gSampler").value, scheduler: $("#gScheduler").value, steps: numOf("#gSteps"), cfg: numOf("#gCfg"), clip: gen.clipSkip };
  const has = (sel, v) => [...$(sel).options].some((o) => o.value === v);
  if (has("#gSampler", r.sampler)) $("#gSampler").value = r.sampler;
  if (has("#gScheduler", r.scheduler)) $("#gScheduler").value = r.scheduler;
  setNum("#gSteps", r.steps); setNum("#gCfg", r.cfg); gen.clipSkip = r.clip_skip;
  saveGen(); updateBatchState();
  const name = model.split(" [")[0].replace(/\.safetensors$/, "");
  toast(`${esc(name)}: ${esc(r.sampler)}${r.scheduler && r.scheduler !== "Automatic" ? " " + esc(r.scheduler) : ""}, ${r.steps} steps, CFG ${r.cfg}, clip skip ${r.clip_skip} <span class="muted">· ${esc(r.source)}</span>`, "info",
    { label: "Undo", fn: () => {
      $("#gSampler").value = before.sampler; $("#gScheduler").value = before.scheduler;
      setNum("#gSteps", before.steps); setNum("#gCfg", before.cfg); gen.clipSkip = before.clip; saveGen(); updateBatchState();
    } });
});

["#gProject", "#gPrompt", "#gNeg", "#gModel", "#gSampler", "#gScheduler", "#gW", "#gH", "#gSeed", "#gCount", "#gHrUp"].forEach((id) =>
  $(id)?.addEventListener("change", () => { syncSize(); saveGen(); }));
$("#gPrompt")?.addEventListener("input", () => renderLoraChips());

let scaleAR = 0;
export function syncSize(fromSlider = false) {
  const w = Number($("#gW")?.value || 0), h = Number($("#gH")?.value || 0);
  $$("#gSize button").forEach((b) => b.classList.toggle("is-on", Number(b.dataset.w) === w && Number(b.dataset.h) === h));
  $("#gSizeLabel").textContent = w && h ? `${w}×${h} · ${(w * h / 1e6).toFixed(1)} MP` : "";
  if (w && h && !fromSlider) {
    scaleAR = w / h;
    const pct = Math.round(Math.sqrt(w * h) / NATIVE * 100);
    $("#gScale").value = Math.max(50, Math.min(200, pct)); $("#gScaleN").value = pct;
  }
}

export function applyScale(pct) {
  const ar = scaleAR || (Number($("#gW").value) / Number($("#gH").value)) || 1;
  let w = (NATIVE * pct / 100) * Math.sqrt(ar), h = w / ar;
  const k = Math.min(1, 2048 / Math.max(w, h)); w *= k; h *= k;
  const snap = (v) => Math.max(256, Math.round(v / 8) * 8);
  $("#gW").value = snap(w); $("#gH").value = snap(h);
  syncSize(true); $("#gScaleN").value = Math.round(pct * k);
  if (k < 1) $("#gScale").value = Math.round(pct * k);
}

$("#gScale")?.addEventListener("input", () => applyScale(Number($("#gScale").value)));
$("#gScale")?.addEventListener("change", saveGen);
$("#gScaleN")?.addEventListener("change", () => { applyScale(Math.max(25, Math.min(250, Number($("#gScaleN").value) || 100))); saveGen(); });
$("#gSize")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-w]"); if (!b) return;
  $("#gW").value = b.dataset.w; $("#gH").value = b.dataset.h; syncSize(); saveGen();
});
$("#gSeedRand")?.addEventListener("click", () => { $("#gSeed").value = ""; saveGen(); });

export function setHires(on) {
  $("#gHires")?.setAttribute("aria-pressed", String(on)); $("#gHires")?.classList.toggle("is-on", on);
  const sc = Number($("#gHrScaleN")?.value || $("#gHrScale")?.value || 1.5);
  $("#gHiresState").textContent = on ? (sc <= 1 ? "on · ×1 detail pass, no upscale" : `on · ×${sc}`) : "off";
  if (on) $("#gHiresBox").open = true;
  updateSubTabIndicators();
}
$("#gHires")?.addEventListener("click", () => { setHires($("#gHires").getAttribute("aria-pressed") !== "true"); saveGen(); });

export function setToggle(id, on) {
  $(id)?.setAttribute("aria-pressed", String(on)); $(id)?.classList.toggle("is-on", on); updateSubTabIndicators();
}
["#gFixBody", "#gFixFace", "#gFixHands"].forEach((id) => $(id)?.addEventListener("click", () => { setToggle(id, $(id).getAttribute("aria-pressed") !== "true"); saveGen(); }));
linkSlider("#gPoseW", "#gPoseWN");
linkSlider("#gDen", "#gDenN");

export function renderGenPoses() {
  $("#gPoseState").textContent = gen.posePack ? (gen.posePack.tags?.slice(0, 3).join(", ") || gen.posePack.pack?.slice(0, 28) || "pose") : "off";
  depthAvail();
  updateSubTabIndicators();
}

export async function setPoseTags(text) {
  const ta = $("#gPrompt"), before = ta.value;
  const on = $("#gPoseTags").getAttribute("aria-pressed") === "true";
  const pose = on ? (text || "") : "";
  if (!pose && !(gen.poseAdded || []).length) return;
  const r = await api("/api/pose/merge", {
    json: {
      prompt: before, pose, drop: gen.poseAdded || [],
      facing_filter: $("#gPoseFacing").getAttribute("aria-pressed") === "true", view: gen.posePack?.tags || null,
    },
  }).catch((e) => (toast(esc(e.message), "err"), null));
  if (!r || ta.value !== before) return;
  const prevAdded = gen.poseAdded;
  gen.poseAdded = r.added;
  ta.value = r.prompt; ta.dispatchEvent(new Event("input")); saveGen();
  if (r.removed.length) toast(`Pose: removed ${r.removed.map(esc).join(", ")} (fights the pose or faces the other way)`, "info",
    { label: "Undo", fn: () => { ta.value = before; gen.poseAdded = prevAdded; ta.dispatchEvent(new Event("input")); saveGen(); } });
}

export function fitToPose(ratio) {
  const r = Math.min(2, Math.max(0.5, ratio || 1));
  const area = (Number($("#gW").value) * Number($("#gH").value)) || NATIVE * NATIVE;
  return [Math.round(Math.sqrt(area * r) / 32) * 32, Math.round(Math.sqrt(area / r) / 32) * 32];
}

export const segVal = (id) => $(`${id} button.is-on`)?.dataset.v;
export function setSeg(id, v) {
  $$(`${id} button`).forEach((b) => { const on = b.dataset.v === String(v); b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", on); });
}

linkSlider("#gDepthW", "#gDepthWN");
["#gDepthW", "#gDepthWN"].forEach((id) => $(id)?.addEventListener("change", saveGen));
$("#gPoseDepth")?.addEventListener("click", () => { gen.depthSet = true; setToggle("#gPoseDepth", $("#gPoseDepth").getAttribute("aria-pressed") !== "true"); depthAvail(); saveGen(); });

export function depthAvail() {
  const has = !!gen.posePack?.depth, on = $("#gPoseDepth")?.getAttribute("aria-pressed") === "true";
  $("#gDepthNote").textContent = !gen.posePack && !gen.poseKey ? (on ? "on for poses marked D" : "off")
    : has ? (on ? "on for this pose" : "off · this pose has one") : "this pose: skeleton only (no depth map)";
  $("#gDepthRow").hidden = !on;
}

["#gPoseMode", "#gPoseMin"].forEach((id) => $(id)?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-v]"); if (b) { setSeg(id, b.dataset.v); saveGen(); }
}));

export function pickGenPose(x) {
  gen.posePack = x; gen.poseKey = null;
  if (x) {
    const [w, h] = fitToPose(x.w / x.h);
    $("#gW").value = w; $("#gH").value = h; syncSize();
  }
  setPoseTags(x?.ptags || "");
  $("#gPoseState").textContent = x ? `${x.tags.slice(0, 3).join(", ") || x.pack.slice(0, 28)}` : "off";
  depthAvail();
  gBrowser.draw(); saveGen();
}

export const poseBatchApi = {
  index: (id) => gen.poseBatch.findIndex((x) => x.id === id),
  size: () => gen.poseBatch.length,
  mode: () => gen.batchMode,
  setMode: (on) => { gen.batchMode = on; },
  toggle: (x) => {
    if (!x) return;
    const i = poseBatchApi.index(x.id);
    if (i >= 0) gen.poseBatch.splice(i, 1);
    else gen.poseBatch.push({ id: x.id, label: x.label, pack: x.pack, ptags: x.ptags || "", tags: x.tags || [], w: x.w, h: x.h, depth: !!x.depth });
    poseBatchChanged();
  },
};

export function poseBatchChanged() {
  try { localStorage.setItem("pl-pose-batch", JSON.stringify(gen.poseBatch)); } catch {}
  renderPoseBatch(); updateBatchState();
  gBrowser.draw();
  if (!$("#poseModal")?.hidden) modalBrowser?.draw();
}

export function renderPoseBatch() {
  const b = gen.poseBatch;
  $("#gPoseBatch").hidden = !b.length;
  if (!b.length) return;
  $("#gPoseBatchNote").textContent = `${b.length} pose${b.length > 1 ? "s" : ""} · one job each${gen.posePack || gen.poseKey ? " (instead of the picked pose)" : ""}`;
  $("#gPoseBatchList").innerHTML = b.map((x, i) => `<span class="pb-chip" title="${esc(x.pack)} · ${esc(x.label)}${x.tags.length ? "\n" + esc(x.tags.join(", ")) : ""}">
    <img loading="lazy" src="/api/posepacks/thumb/${x.id}" alt=""><b>${i + 1}</b><button class="pb-x" data-rm="${x.id}" aria-label="Remove pose ${i + 1} from the batch" title="Remove"><i class="ph ph-x"></i></button></span>`).join("");
}

export const gBrowser = packBrowser($("#gPacks"), pickGenPose, () => gen.posePack?.id, { batch: poseBatchApi });

$("#gPoseBatchList")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-rm]"); if (!b) return;
  gen.poseBatch = gen.poseBatch.filter((x) => x.id !== b.dataset.rm); poseBatchChanged();
});
$("#gPoseBatchClear")?.addEventListener("click", () => { gen.poseBatch = []; gen.batchMode = false; poseBatchChanged(); });
renderPoseBatch();

$("#gPoseBox")?.addEventListener("toggle", () => { if ($("#gPoseBox").open && !gBrowser.loaded) { gBrowser.loaded = true; gBrowser.load(); } });
$("#gPoseFacing")?.addEventListener("click", () => {
  const on = $("#gPoseFacing").getAttribute("aria-pressed") !== "true"; setToggle("#gPoseFacing", on); saveGen();
  if (on && gen.posePack) setPoseTags(gen.posePack.ptags || "");
});
$("#gPoseTags")?.addEventListener("click", () => {
  const on = $("#gPoseTags").getAttribute("aria-pressed") !== "true"; setToggle("#gPoseTags", on);
  setPoseTags(on ? (gen.posePack?.ptags || "") : "");
});

export async function setRemixFile(file) {
  if (!file?.type?.startsWith("image/")) return toast("That isn't an image file. Drop a PNG, JPG or WebP instead.", "err");
  const r = await fetch("/api/gen/input", { method: "POST", body: file }).then((x) => x.json());
  if (!r.name) return toast("Couldn't read that image. Use a PNG, JPG or WebP file.", "err");
  setRemix(r);
}

export function setRemix(r) {
  gen.remix = r;
  $("#gRemixImg").src = r ? (r.name.startsWith("in-") ? `/api/gen/input/${r.name}` : `/api/gen/image/${r.name}`) : "";
  $("#gRemixImg").hidden = !r; $("#gRemixDrop .dz-empty").hidden = !!r;
  $("#gRemixState").textContent = r ? `on · ${r.width}×${r.height}` : "off";
  if (r) { $("#gRemixBox").open = true; $("#gW").value = r.width; $("#gH").value = r.height; syncSize(); }
  updateSubTabIndicators();
}

const rd = $("#gRemixDrop");
rd?.addEventListener("dragover", (e) => { e.preventDefault(); rd.classList.add("drag"); });
rd?.addEventListener("dragleave", () => rd.classList.remove("drag"));
rd?.addEventListener("drop", (e) => { e.preventDefault(); rd.classList.remove("drag"); setRemixFile(e.dataTransfer.files[0]); });
$("#gRemixFile")?.addEventListener("change", (e) => setRemixFile(e.target.files[0]));
$("#gRemixClear")?.addEventListener("click", (e) => { e.preventDefault(); setRemix(null); });
$("#gRemixInterrogate")?.addEventListener("click", async (e) => {
  e.preventDefault();
  if (!gen.remix?.name) return toast("Drop or select an image in Remix first", "info");
  try {
    const url = gen.remix.name.startsWith("in-") ? `/api/gen/input/${gen.remix.name}` : `/api/gen/image/${gen.remix.name}`;
    const blob = await fetch(url).then((r) => r.blob());
    const file = new File([blob], "remix.png", { type: blob.type || "image/png" });
    showView("interrogate");
    pickImage(file);
    toast("Image loaded into Interrogate", "info");
    $("#irun")?.click();
  } catch (err) {
    toast(`Couldn't interrogate remix image: ${err.message}`, "err");
  }
});

export const LORA_RX = /<lora:([^:>]+):([\d.]+)>/g;
export function renderLoraChips() {
  const promptEl = $("#gPrompt");
  if (!promptEl) return;
  const found = [...promptEl.value.matchAll(LORA_RX)];
  $("#gLoras").innerHTML = found.map((m) => `
    <span class="chip static lora-chip"><i class="ph ph-puzzle-piece"></i>${esc(m[1])}
      <input type="range" min="0" max="1.5" step="0.05" value="${m[2]}" data-lora="${esc(m[1])}" title="Weight">
      <b>${Number(m[2]).toFixed(2)}</b><button data-rmlora="${esc(m[1])}" title="Remove"><i class="ph ph-x"></i></button></span>`).join("");
}

$("#gLoras")?.addEventListener("input", (e) => {
  const r = e.target.closest("[data-lora]"); if (!r) return;
  const name = r.dataset.lora, w = Number(r.value).toFixed(2);
  r.nextElementSibling.textContent = w;
  $("#gPrompt").value = $("#gPrompt").value.replace(new RegExp(`<lora:${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:[\\d.]+>`), `<lora:${name}:${w}>`);
  saveGen();
});
$("#gLoras")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-rmlora]"); if (!b) return;
  const name = b.dataset.rmlora.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  $("#gPrompt").value = $("#gPrompt").value.replace(new RegExp(`,?\\s*<lora:${name}:[\\d.]+>`), "").trim();
  renderLoraChips(); saveGen();
});
$("#gLoraQ")?.addEventListener("change", (e) => {
  const name = e.target.value.trim();
  const o = gen.opts || {};
  const list = o.loras || [];
  if (!name || !list.includes(name)) return;
  const p = $("#gPrompt").value.trim();
  if (!p.includes(`<lora:${name}:`)) $("#gPrompt").value = (p ? p + ", " : "") + `<lora:${name}:0.8>`;
  e.target.value = ""; renderLoraChips(); saveGen();
});

export function refreshLoraList() {
  if (!gen.opts) return;
  const dl = $("#gLoraList");
  if (dl) dl.innerHTML = (gen.opts.loras || []).map((l) => `<option value="${esc(l)}">`).join("");
}

export async function loadGenOptions() {
  const o = await api("/api/gen/options").catch((e) => ({ online: false, error: e.message }));
  let saved = {}; try { saved = JSON.parse(localStorage.getItem(PREFS_GEN) || "{}"); } catch {}
  gen.opts = o;
  syncBackendUi();
  refreshLoraList();
  if (!o.online) {
    $("#gEmptyText").innerHTML = forge.state === "starting" ? "Forge is starting. Generate unlocks when it's ready."
      : `Generate needs Forge running.<br><button class="btn btn-primary" id="gStartForge"><i class="ph ph-power"></i>Start Forge</button>`;
    $("#gStartForge")?.addEventListener("click", () => {
      import("../main.js").then((m) => m.toggleForge());
    });
    applyParams({ steps: 25, cfg: 6, width: 832, height: 1216, count: 1, hr_scale: 1.5, hr_denoise: 0.4, hr_steps: 0, ...saved, ...(gen.pending || {}) });
    gen.pending = null;
    syncBackendUi();
    if (!gen.polling) { $("#gEmpty").hidden = false; }
    return;
  }
  $("#gEmptyText").textContent = "Your images appear here.";
  const families = {};
  for (const st of o.styles) (families[st.name.includes(" · ") ? st.name.split(" · ")[0] : "Other"] ??= []).push(st);
  $("#gStyle").innerHTML = `<option value="">None (manual settings)</option>` +
    Object.entries(families).map(([fam, list]) => `<optgroup label="${esc(fam)}">` + list.map((st) =>
      `<option value="${esc(st.name)}">${esc(st.name.includes(" · ") ? st.name.split(" · ").slice(1).join(" · ") : st.name)}${st.missing.length ? " (missing files)" : ""}</option>`).join("") + `</optgroup>`).join("");
  fillSelect($("#gModel"), o.models, o.model);
  fillSelect($("#gSampler"), o.samplers, "Euler a");
  fillSelect($("#gScheduler"), o.schedulers, "Automatic");
  fillSelect($("#gHrUp"), o.upscalers, o.upscalers.find((u) => /4x|ultrasharp|esrgan/i.test(u)) || o.upscalers[0]);
  refreshLoraList();
  renderCompare(); fillCollections(); renderGenPoses(); startPolling();
  applyParams({ steps: 25, cfg: 6, width: 832, height: 1216, count: 1, hr_scale: 1.5, hr_denoise: 0.4, hr_steps: 0, ...saved, ...(gen.pending || {}) });
  gen.pending = null;
  if (!$("#gModel").value && o.models.length) $("#gModel").value = o.models.includes(o.model) ? o.model : o.models[0];
  if (!o.models.length) setTimeout(loadGenOptions, 5000);
}

function syncBackendUi() {
  const forgeOnline = !!gen.opts?.online;
  $("#gRun").disabled = !forgeOnline;
  $("#gBackendInfo").innerHTML = "Forge uses the shared Forge connection. Manage Forge from Spellbook UI.";
  if (!gen.polling) $("#gEmpty").hidden = forgeOnline;
}

export const WILD = /\{([^{}|]+(?:\|[^{}|]+)+)\}/g;
export function wildcardOptions(prompt) { return [...prompt.matchAll(WILD)].map((m) => m[1].split("|").map((x) => x.trim())); }
export function expandWild(prompt, mode, count) {
  const opts = wildcardOptions(prompt);
  if (!opts.length) return null;
  const fill = (picks) => { let i = 0; return prompt.replace(WILD, () => picks[i++]); };
  if (mode === "all") {
    let combos = [[]];
    for (const o of opts) combos = combos.flatMap((c) => o.map((x) => [...c, x]));
    return combos.slice(0, 64).map(fill);
  }
  return Array.from({ length: count }, () => fill(opts.map((o) => o[Math.floor(Math.random() * o.length)])));
}

export function selectedCompare() { return $$("#gCmp input:checked").map((c) => c.value); }
export function buildJobs(p) {
  const styles = selectedCompare();
  const wild = expandWild(p.prompt, $("#gWildMode .is-on")?.dataset.v || "random", p.count);
  const prompts = wild ? wild.map((x) => ({ prompt: x, count: 1 })) : [{ prompt: p.prompt, count: p.count }];
  const variants = styles.length ? styles : [p.style];
  const jobs = [];
  for (const sty of variants) {
    const st = (gen.opts?.styles || []).find((x) => x.name === sty);
    for (const pr of prompts) {
      const params = { ...p, prompt: pr.prompt, count: pr.count, style: sty || "" };
      if (styles.length && st) Object.assign(params, {
        model: st.model || p.model, sampler: st.sampler, scheduler: st.scheduler,
        steps: st.steps, cfg: st.cfg, clip_skip: st.clip_skip,
      });
      jobs.push({ params, label: pr.prompt.replace(/<lora:[^>]+>/g, "").slice(0, 80) });
    }
  }
  if (!gen.poseBatch?.length || p.mode === "img2img") return jobs;
  return jobs.flatMap((j) => gen.poseBatch.map((x) => {
    const [width, height] = fitToPose(x.w / x.h);
    return { params: { ...j.params, pose_key: null, pose_pack_id: x.id, width, height }, label: `${x.label.slice(0, 28)} · ${j.label}`, pose: x };
  }));
}

export async function poseBatchPrompts(jobs) {
  const on = $("#gPoseTags").getAttribute("aria-pressed") === "true", facing = $("#gPoseFacing").getAttribute("aria-pressed") === "true";
  const memo = new Map();
  for (const j of jobs) {
    if (!j.pose) continue;
    const key = j.params.prompt + "\u0000" + j.pose.id;
    if (!memo.has(key)) memo.set(key, api("/api/pose/merge", {
      json: {
        prompt: j.params.prompt, pose: on ? j.pose.ptags : "", drop: gen.poseAdded || [],
        facing_filter: facing, view: j.pose.tags,
      },
    }).then((r) => r.prompt));
    j.params.prompt = await memo.get(key);
    delete j.pose;
  }
  return jobs;
}

export function updateBatchState() {
  const p = genParams();
  const jobs = p.prompt ? buildJobs(p) : [];
  const imgs = jobs.reduce((n, j) => n + j.params.count, 0);
  const opts = wildcardOptions(p.prompt);
  $("#gWildInfo").textContent = opts.length ? `${opts.length} wildcard${opts.length > 1 ? "s" : ""}, ${opts.reduce((n, o) => n * o.length, 1)} combinations` : "none in prompt";
  const np = p.mode !== "img2img" ? gen.poseBatch?.length || 0 : 0;
  $("#gBatchState").textContent = (jobs.length > 1 ? `${jobs.length} jobs · ${imgs} images` : `${imgs || 1} image${imgs > 1 ? "s" : ""}`) + (np ? ` · ${np} poses` : "");
  const avg = gen.avgImage;
  $("#gRun").title = avg && imgs ? `About ${fmtTime(avg * imgs)} at your recent speed` : "";
  updateSubTabIndicators();
}

export function renderCompare() {
  const q = $("#gCmpQ")?.value.trim().toLowerCase() || "";
  const sel = new Set(selectedCompare());
  $("#gCmp").innerHTML = (gen.opts?.styles || []).filter((st) => !q || st.name.toLowerCase().includes(q) || sel.has(st.name)).map((st) =>
    `<label><input type="checkbox" value="${esc(st.name)}" ${sel.has(st.name) ? "checked" : ""}>${esc(st.name)}${st.missing.length ? "<small>missing files</small>" : ""}</label>`).join("");
}

$("#gCmpQ")?.addEventListener("input", renderCompare);
$("#gCmp")?.addEventListener("change", updateBatchState);
$("#gWildMode")?.addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (!b) return; $$("#gWildMode button").forEach((x) => x.classList.toggle("is-on", x === b)); updateBatchState(); });
$("#gPrompt")?.addEventListener("input", updateBatchState);
$("#gCount")?.addEventListener("input", updateBatchState);
$$(".stepper [data-step]").forEach((b) => b.addEventListener("click", () => {
  const c = $("#gCount"); c.value = Math.max(1, Math.min(16, Number(c.value || 1) + Number(b.dataset.step))); saveGen(); updateBatchState();
}));
$("#gSeedLast")?.addEventListener("click", () => { const g = gen.gallery[0]; if (!g) return toast("No images yet", "info"); $("#gSeed").value = g.seed; saveGen(); toast(`Seed ${g.seed}`, "info"); });

$("#gAwake")?.addEventListener("click", async () => {
  const on = $("#gAwake").getAttribute("aria-pressed") !== "true"; setToggle("#gAwake", on);
  await api("/api/gen/notify", { json: { awake: on } });
});
$("#gNotify")?.addEventListener("click", async () => {
  const on = $("#gNotify").getAttribute("aria-pressed") !== "true";
  $("#gNotify").setAttribute("aria-pressed", String(on)); $("#gNotify").classList.toggle("is-on", on);
  await api("/api/gen/notify", { json: { on } });
});

export function fillCollections() {
  const cols = state.meta?.collections || [];
  $("#gColl").innerHTML = cols.map((c) => `<option value="${esc(c)}">${esc(label(c))}</option>`).join("");
}

$("#gCollRun")?.addEventListener("click", async () => {
  const col = $("#gColl").value; if (!col) return;
  const res = await api(`/api/search?${new URLSearchParams({ collection: col, rating: "All (incl. mature)", per_page: 480 })}`);
  if (!res.items.length) return toast("That collection is empty", "info");
  const base = genParams();
  const jobs = [];
  for (const it of res.items) {
    const r = await api(`/api/record/${it.id}/gen`).catch(() => null);
    if (r) jobs.push({ params: { ...base, prompt: r.prompt, negative: base.style ? "" : r.negative, seed: -1, count: 1 }, label: `#${it.id} · ${r.prompt.slice(0, 60)}` });
  }
  await api("/api/gen/run", { json: { jobs } });
  toast(`Queued ${jobs.length} prompts from ${esc(label(col))}`);
  startPolling();
});

export async function cleanPromptBox(sel, negative, quiet = false) {
  const ta = $(sel), before = ta?.value;
  if (!before?.trim()) return;
  const pose = negative ? "" : gen.posePack?.ptags || state.meta?.poses?.find((x) => x.key === gen.poseKey)?.tags || "";
  const r = await api("/api/clean", { json: { text: before, negative, framing: !negative, auto: true, pose } }).catch(() => null);
  if (!r || !r.notes.length || ta.value !== before || r.text === before) return;
  ta.value = r.text; ta.dispatchEvent(new Event("input")); saveGen();
  if (!quiet) {
    const dups = r.notes.filter((n) => n.startsWith("dup ")).map((n) => n.slice(4));
    const other = r.notes.filter((n) => !n.startsWith("dup "));
    toast(`Cleaned ${negative ? "negative" : "prompt"}: ${[dups.length ? `removed duplicate ${dups.map(esc).join(", ")}` : "", ...other.map(esc)].filter(Boolean).join(" · ")}`,
      "info", { label: "Undo", fn: () => { ta.value = before; ta.dispatchEvent(new Event("input")); saveGen(); } });
  }
}

$("#gPrompt")?.addEventListener("blur", () => cleanPromptBox("#gPrompt", false));
$("#gNeg")?.addEventListener("blur", () => cleanPromptBox("#gNeg", true));

export async function runGen() {
  if ($("#gRun")?.disabled) return;
  await Promise.all([cleanPromptBox("#gPrompt", false, true), cleanPromptBox("#gNeg", true, true)]);
  const p = genParams();
  if (gen.variation) {
    p.variation = true;
    gen.variation = false;
  }
  if (!p.prompt) return toast("Write a prompt first", "err");
  saveGen();
  let jobs = buildJobs(p);
  try {
    if (jobs.some((j) => j.pose)) jobs = await poseBatchPrompts(jobs);
    tagComparison(jobs);
    await api("/api/gen/run", { json: { jobs } });
  } catch (e) { return toast(esc(e.message), "err"); }
  const imgs = jobs.reduce((n, j) => n + j.params.count, 0);
  const cid = jobs[0]?.params.compare?.id;
  if (cid) toast(`Queued a comparison: ${jobs.length} jobs · ${imgs} image${imgs > 1 ? "s" : ""}${jobs[0].params.compare.seed != null ? ` · seed ${jobs[0].params.compare.seed}` : ""}`, "info",
    { label: "Open comparison", fn: () => openCmpGrid(cid) });
  else if (gen.polling || jobs.length > 1) toast(`Queued ${jobs.length} job${jobs.length > 1 ? "s" : ""} · ${imgs} image${imgs > 1 ? "s" : ""}`, "info");
  startPolling();
}

$("#gRun")?.addEventListener("click", runGen);
$("#gStop")?.addEventListener("click", async () => { await api("/api/gen/interrupt", { method: "POST" }); toast("Stopping the current image", "info"); });
$("#gQueueCancel")?.addEventListener("click", async () => { await api("/api/gen/cancel", { json: {} }); toast("Cancelling the queue", "info"); });
$("#gQueuePauseAfter")?.addEventListener("click", async () => {
  const isCurrentlyOn = $("#gQueuePauseAfter").classList.contains("is-on");
  const willBeOn = !isCurrentlyOn;
  await api("/api/gen/pause-after", { json: { on: willBeOn } });
  $("#gQueuePauseAfter").classList.toggle("is-on", willBeOn);
  toast(willBeOn ? "Queue will pause after current image" : "Queue will continue", "info");
  startPolling();
});
$("#gQueueResume")?.addEventListener("click", async () => {
  if (!gen.opts?.online) return toast("Start Forge first, then Resume.", "err");
  const r = await api("/api/gen/resume", { method: "POST" }); toast(`Resumed ${r.resumed} job${r.resumed !== 1 ? "s" : ""}`); startPolling();
});
$("#gQueueDiscard")?.addEventListener("click", async () => {
  if (!(await confirmDialog("Discard the jobs saved from your last session?"))) return;
  const held = (gen.lastProgress?.queue || []).filter((j) => j.status === "held");
  for (const j of held) await api("/api/gen/cancel", { json: { id: j.id } });
  await api("/api/gen/clear", { method: "POST" }); startPolling();
});
$("#gQueueClear")?.addEventListener("click", async () => { await api("/api/gen/clear", { method: "POST" }); startPolling(); });
$("#gQueueList")?.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cancel]"); if (b) { await api("/api/gen/cancel", { json: { id: b.dataset.cancel } }); startPolling(); }
});

export const fmtTime = (s) => (s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`);
export function startPolling() { if (!gen.polling) pollGen(); }

export function renderGenStatus() {
  const p = gen.lastProgress || {}, away = state.view !== "generate";
  const busy = p.running || (p.queue || []).some((j) => j.status === "queued");
  const badge = $("#genBadge");
  if (badge) {
    if (busy) { badge.hidden = false; badge.textContent = p.left_images || "•"; badge.className = "rail-badge busy"; badge.title = `${p.left_images} image${p.left_images !== 1 ? "s" : ""} to go`; }
    else if (away && gen.unseen) { badge.hidden = false; badge.textContent = gen.unseen; badge.className = "rail-badge new"; badge.title = `${gen.unseen} new image${gen.unseen !== 1 ? "s" : ""}`; }
    else badge.hidden = true;
  }
  const pill = $("#genPill");
  if (!pill) return;
  if (!away || gen.pillHidden || !(busy || gen.unseen)) { pill.hidden = true; return; }
  pill.hidden = false;
  const pct = Math.round((p.progress || 0) * 100);
  if (busy) {
    $("#genPillTitle").textContent = p.running ? (p.step != null && p.steps ? `Generating · image ${Math.min(p.image_no, p.total)} of ${p.total} · ${pct}%` : "Starting…") : "Queued";
    const jobs = (p.queue || []).filter((j) => ["queued", "running"].includes(j.status)).length;
    const saving = p.running && !p.eta && pct >= 95;  // sampling done; decoding/saving (no ETA yet)
    const avg = p.avg_image_seconds;
    const timePart = p.eta ? `about ${fmtTime(p.eta)} left`
      : saving ? "finishing up · saving the image"
      : avg ? `~${fmtTime(Math.max(0, avg * (p.left_images - (pct / 100))))} left`
      : "";
    $("#genPillSub").textContent = [timePart,
      `${p.left_images} image${p.left_images !== 1 ? "s" : ""} to go`,
      jobs > 1 ? `${jobs} jobs` : "", gen.unseen ? `${gen.unseen} new` : "",
      saving && p.elapsed != null ? `${fmtTime(p.elapsed)} elapsed` : ""].filter(Boolean).join(" · ");
    $("#genPillBar").style.transform = `scaleX(${p.running ? pct / 100 : 0})`;
    const img = p.preview || (gen.lastNew && `/api/gen/image/${gen.lastNew}`);
    $("#genPillImg").hidden = !img; if (img) $("#genPillImg").src = img;
  } else {
    $("#genPillTitle").textContent = `Done · ${gen.unseen} new image${gen.unseen !== 1 ? "s" : ""}`;
    $("#genPillSub").textContent = "Click to see them in Generate";
    $("#genPillBar").style.transform = "scaleX(1)";
    $("#genPillImg").hidden = !gen.lastNew; if (gen.lastNew) $("#genPillImg").src = `/api/gen/image/${gen.lastNew}`;
  }
  pill.classList.toggle("done", !busy);
}

$("#genPill")?.addEventListener("click", (e) => {
  if (e.target.closest("#genPillClose")) { gen.pillHidden = true; renderGenStatus(); return; }
  showView("generate");
});

export const Q_ICON = {
  queued: "ph-clock", running: "ph-circle-notch spin", done: "ph-check-circle",
  error: "ph-warning-circle", cancelled: "ph-x-circle", cancelling: "ph-circle-notch spin", held: "ph-pause-circle",
};

export function qIcon(j) {
  const prev = gen.qStatus.get(j.id);
  gen.qStatus.set(j.id, j.status);
  const now = `<i class="ph ${Q_ICON[j.status] || "ph-clock"} q-icon" aria-hidden="true"></i>`;
  if (!prev || prev === j.status) return now;
  return `<i class="ph ${Q_ICON[prev] || "ph-clock"} q-icon q-out" aria-hidden="true"></i>${now.replace("q-icon", "q-icon q-in")}`;
}

export function renderQueue(p) {
  const q = p.queue || [];
  $("#gQueue").hidden = !q.length;
  const left = q.filter((j) => j.status === "queued").length;
  const eta = p.avg_image_seconds && p.left_images ? ` · about ${fmtTime(p.avg_image_seconds * p.left_images)} left` : "";
  $("#gQueueInfo").textContent = p.running || left ? `${left + (p.running ? 1 : 0)} job${left + (p.running ? 1 : 0) !== 1 ? "s" : ""} · ${p.left_images} image${p.left_images !== 1 ? "s" : ""} to go${eta}` : "All done";
  $("#gQueueCancel").hidden = !(p.running || left);
  const held = q.filter((j) => j.status === "held");
  $("#gQueueResume").hidden = $("#gQueueDiscard").hidden = !held.length;
  const pBtn = $("#gQueuePauseAfter");
  if (pBtn) {
    pBtn.hidden = !(p.running && left);
    pBtn.classList.toggle("is-on", !!p.pause_after);
    pBtn.title = p.pause_after ? "Will pause queue when current image finishes (click to resume normal queue)" : "Finish current image, then pause queue";
  }
  if (held.length && !p.running && !left) {
    const n = held.reduce((a, j) => a + (j.total || 1), 0);
    $("#gQueueInfo").textContent = `${held.length} job${held.length !== 1 ? "s" : ""} (${n} image${n !== 1 ? "s" : ""}) saved from your last session`;
  }
  gen.qSeen = gen.qSeen || new Set();
  const html = q.map((j) => `
    <li class="${j.status}${gen.qSeen.has(j.id) ? "" : " q-new"}" data-id="${j.id}" ${j.status === "queued" ? 'draggable="true"' : ""} title="${esc(j.error || j.label)}"><span class="q-icon-wrap">${qIcon(j)}</span>
      <span class="q-label">${esc(j.label)}</span>${j.style ? `<span class="q-style">${esc(j.style)}</span>` : ""}
      <span class="q-thumbs">${j.results.slice(0, 4).map((n) => `<img src="/api/gen/thumb/${n}" alt="" loading="lazy" decoding="async">`).join("")}</span>
      <span class="q-count">${j.results.length || 0}/${j.total}</span>
      ${["queued", "running", "held"].includes(j.status) ? `<button class="icon-btn" data-cancel="${j.id}" title="Cancel this job" aria-label="Cancel this job"><i class="ph ph-x"></i></button>` : ""}
    </li>`).join("");
  q.forEach((j) => gen.qSeen.add(j.id));
  if (html !== gen.qHtml) { gen.qHtml = html; $("#gQueueList").innerHTML = html; }
}

let dragJobId = null;
$("#gQueueList")?.addEventListener("dragstart", (e) => {
  const li = e.target.closest("li[data-id]");
  if (!li || li.getAttribute("draggable") !== "true") return;
  dragJobId = li.dataset.id;
  li.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", dragJobId);
});
$("#gQueueList")?.addEventListener("dragend", () => {
  dragJobId = null;
  $$("#gQueueList li").forEach((el) => el.classList.remove("dragging", "drag-over"));
});
$("#gQueueList")?.addEventListener("dragover", (e) => {
  if (!dragJobId) return;
  const li = e.target.closest("li[data-id]");
  if (!li || li.getAttribute("draggable") !== "true") return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  $$("#gQueueList li").forEach((el) => el.classList.toggle("drag-over", el === li));
});
$("#gQueueList")?.addEventListener("dragleave", (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) li.classList.remove("drag-over");
});
$("#gQueueList")?.addEventListener("drop", async (e) => {
  e.preventDefault();
  const targetLi = e.target.closest("li[data-id]");
  $$("#gQueueList li").forEach((el) => el.classList.remove("dragging", "drag-over"));
  if (!targetLi || !dragJobId || targetLi.dataset.id === dragJobId) return;
  const queuedLis = [...$$("#gQueueList li[draggable='true']")];
  const ids = queuedLis.map((el) => el.dataset.id);
  const fromIdx = ids.indexOf(dragJobId);
  const toIdx = ids.indexOf(targetLi.dataset.id);
  if (fromIdx < 0 || toIdx < 0) return;
  ids.splice(fromIdx, 1);
  ids.splice(toIdx, 0, dragJobId);
  try {
    await api("/api/gen/reorder", { json: { ids } });
    gen.qHtml = null;
    await pollGen();
  } catch (err) {
    toast(esc(err.message), "err");
  }
});

export async function pollGen() {
  gen.polling = true;
  try {
    const wantPreview = !document.hidden && (state.view === "generate" || !gen.pillHidden);
    const p = await api(`/api/gen/progress?preview=${wantPreview ? "true" : "false"}`);
    gen.avgImage = p.avg_image_seconds;
    renderQueue(p);
    const doneNow = (p.queue || []).reduce((n, j) => n + j.results.length, 0);
    if (doneNow !== gen.doneCount) {
      if (gen.doneCount != null && doneNow > gen.doneCount && state.view !== "generate") {
        gen.unseen = (gen.unseen || 0) + doneNow - gen.doneCount;
        gen.lastNew = (p.queue || []).flatMap((j) => j.results).slice(-1)[0];
        gen.pillHidden = false;
      }
      gen.doneCount = doneNow; renderGallery({ refresh: true });
    }
    gen.lastProgress = p; renderGenStatus();
    const busy = p.running || (p.queue || []).some((j) => j.status === "queued");
    const runBtn = $("#gRun");
    if (runBtn && runBtn.dataset.busy !== String(busy)) {
      runBtn.dataset.busy = String(busy);
      runBtn.innerHTML = busy ? `<i class="ph ph-plus-circle"></i>Add to queue<kbd>⌘↵</kbd>` : `<i class="ph ph-sparkle"></i>Generate<kbd>⌘↵</kbd>`;
    }
    $("#gStop").hidden = !p.running;
    if (p.running) {
      $("#gProg").hidden = false; $("#gEmpty").hidden = true;
      const pct = Math.round((p.progress || 0) * 100);
      $("#gBar").style.transform = `scaleX(${pct / 100})`;
      $("#gProgText").textContent = p.step != null && p.steps ? `Image ${Math.min(p.image_no, p.total)} of ${p.total} · step ${p.step}/${p.steps} · ${pct}%` : `Starting… ${fmtTime(p.elapsed)} (loading the model can take a minute)`;
      if (!p.eta && pct >= 95 && p.avg_image_seconds != null) {
        $("#gProgText").textContent = `Image ${Math.min(p.image_no, p.total)} of ${p.total} · finishing up (saving the image)`;
        $("#gEta").textContent = `last image took ~${fmtTime(p.avg_image_seconds)} · ${fmtTime(p.elapsed)} elapsed`;
      } else $("#gEta").textContent = p.eta ? `about ${fmtTime(p.eta)} left` : "";
      if (p.preview) { $("#gPreview").src = p.preview; $("#gPreview").hidden = false; }
    } else $("#gProg").hidden = true;
    const failed = (p.queue || []).filter((j) => j.status === "error" && !gen.seenErr?.has(j.id));
    gen.seenErr = gen.seenErr || new Set();
    failed.forEach((j) => { gen.seenErr.add(j.id); toast(esc(j.error || "A job failed"), "err"); });
    if (busy) { gen.wasBusy = true; setTimeout(pollGen, document.hidden ? 4000 : 1200); return; }
    gen.polling = false;
    if (gen.wasBusy) { toast("Queue finished"); gen.finished = true; renderGenStatus(); }
    gen.wasBusy = false;
  } catch (e) { gen.polling = false; toast(esc(e.message), "err"); return; }
}

export function filteredGallery() {
  const style = $("#gGalStyle")?.value || "", days = $("#gGalDate")?.value || "all", proj = $("#gGalProj")?.value || "";
  const since = days === "all" ? 0 : Date.now() / 1000 - Number(days) * 86400;
  return gen.gallery.filter((g) => (gen.galStar === "all" || g.starred) && (!style || (g.params?.style || "") === style || (style === "-" && !g.params?.style))
    && (!since || (g.time || 0) >= since) && (!proj || (g.params?.project || "") === proj));
}

export const poseWrong = (g) => /^wrong/.test(g.pose_facing || "");
export function poseBadge(g) {
  if (g.pose_score == null && !poseWrong(g)) return "";
  const cls = poseWrong(g) ? "low" : poseClass(g.pose_score);
  const label = poseWrong(g) ? (g.pose_facing.startsWith("wrong") ? "Wrong way" : "No body") : `${g.pose_score}%`;
  const tip = `Pose match: how closely the body follows the skeleton${g.pose_facing ? ` · facing ${g.pose_facing}` : ""}${g.pose_attempt ? ` · retry ${g.pose_attempt - 1}` : ""}`;
  return `<span class="gal-pose ${cls}" title="${esc(tip)}"><i class="ph ph-person-simple"></i>${esc(label)}</span>`;
}

function setSelectIfChanged(el, html, value) {
  if (!el) return;
  if (el.dataset.opts !== html) { el.dataset.opts = html; el.innerHTML = html; }
  if (value !== undefined) el.value = value;
}

export async function renderGallery({ refresh = true } = {}) {
  const before = gen.gallery?.[0]?.name;
  if (refresh || !gen.galLoaded) {
    gen.gallery = await api("/api/gen/history").catch(() => []);
    gen.galLoaded = true;
  }
  if (gen.gallery[0] && gen.gallery[0].name !== before && before !== undefined) {
    const pv = $("#gPreview"); pv.src = `/api/gen/image/${gen.gallery[0].name}`; pv.hidden = false;
    pv.classList.remove("swap"); void pv.offsetWidth; pv.classList.add("swap"); $("#gEmpty").hidden = true;
  }
  const styles = [...new Set(gen.gallery.map((g) => g.params?.style || ""))];
  const cur = $("#gGalStyle")?.value;
  const styleHtml = `<option value="">Any style</option>` + (styles.includes("") ? `<option value="-">No style</option>` : "")
    + styles.filter(Boolean).sort().map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  const styleOk = cur === "" || (cur === "-" && styles.includes("")) || styles.includes(cur);
  setSelectIfChanged($("#gGalStyle"), styleHtml, styleOk ? cur : "");
  const projects = [...new Set(gen.gallery.map((g) => g.params?.project).filter(Boolean))].sort();
  const curP = $("#gGalProj")?.value;
  setSelectIfChanged($("#gGalProj"), `<option value="">Any project</option>` + projects.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join(""), projects.includes(curP) ? curP : "");
  $("#gGalProj").hidden = !projects.length;
  setSelectIfChanged($("#gProjList"), projects.map((x) => `<option value="${esc(x)}">`).join(""));
  drawGallery();
  renderLbStrip();
  if (!gen.polling && $("#gPreview")?.hidden && gen.gallery[0]) { $("#gPreview").src = `/api/gen/image/${gen.gallery[0].name}`; $("#gPreview").hidden = false; $("#gEmpty").hidden = true; }
}

export function markFresh() {
  const names = gen.gallery.map((g) => g.name);
  if (gen.seen === null) { gen.seen = new Set(names); return; }
  names.forEach((n) => { if (!gen.seen.has(n)) { gen.seen.add(n); gen.fresh.add(n); } });
}

export function drawGallery() {
  markFresh();
  const list = filteredGallery();
  gen.view = list;
  $("#gGalCount").textContent = gen.gallery.length ? (list.length === gen.gallery.length ? `${list.length} images` : `${list.length} of ${gen.gallery.length}`) : "";
  $("#gGal").classList.toggle("selecting", $("#gGalSelect")?.getAttribute("aria-pressed") === "true");
  const html = list.length ? list.map((g, i) => `
    <button class="gal-item${gen.picked.has(g.name) ? " picked" : ""}${gen.fresh.has(g.name) ? " fresh" : ""}${gen.fresh.has(g.name) && !gen.entered.has(g.name) ? " arriving" : ""}" data-i="${i}" data-name="${g.name}" title="Seed ${esc(g.seed)}${gen.fresh.has(g.name) ? " · new" : ""}">
      <img loading="lazy" fetchpriority="${i < 12 ? "high" : "auto"}" decoding="async" src="/api/gen/thumb/${g.name}" alt="">
      ${gen.fresh.has(g.name) ? `<span class="gal-new" title="New image">New</span>` : ""}
      <span class="gal-check"><i class="ph ph-check"></i></span>
      ${g.starred ? `<span class="gal-star"><i class="ph-fill ph-star"></i></span>` : ""}
      ${poseBadge(g)}
      ${g.params?.mode === "fix" ? `<span class="gal-tag">Fixed ${["body", "face", "hands"].filter((k) => g.params["fix_" + k]).join(" + ")}</span>` : g.params?.mode === "upscale" ? `<span class="gal-tag">Upscaled ×${esc(g.params.scale)}</span>` : g.params?.style ? `<span class="gal-tag">${esc(g.params.style)}</span>` : ""}
    </button>`).join("")
    : gen.gallery.length
      ? `<div class="empty compact"><p>No images match these filters.</p><button class="btn btn-sm" data-gclear>Clear gallery filters</button></div>`
      : `<div class="empty compact"><i class="ph ph-sparkle" aria-hidden="true"></i><h3>Nothing generated yet</h3><button class="btn btn-primary" data-gstart><i class="ph ph-magic-wand"></i>Start with the prompt</button><p>Write one here, or pick a prompt in the Library and press Open in Generate.</p></div>`;
  if (html !== gen.galHtml) { gen.galHtml = html; $("#gGal").innerHTML = html; }
  list.forEach((g) => gen.fresh.has(g.name) && gen.entered.add(g.name));
  $("#gGalActions").hidden = !$("#gGal").classList.contains("selecting");
  $("#gGalSelCount").textContent = `${gen.picked.size} selected`;
}

$("#gGalStar")?.addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (!b) return; gen.galStar = b.dataset.v; $$("#gGalStar button").forEach((x) => x.classList.toggle("is-on", x === b)); drawGallery(); });
$("#gGalStyle")?.addEventListener("change", drawGallery);
$("#gGalDate")?.addEventListener("change", drawGallery);
$("#gGalProj")?.addEventListener("change", drawGallery);
$("#gGalSelect")?.addEventListener("click", () => { const on = $("#gGalSelect").getAttribute("aria-pressed") !== "true"; setToggle("#gGalSelect", on); if (!on) gen.picked.clear(); drawGallery(); });
$("#gGal")?.addEventListener("click", (e) => {
  if (e.target.closest("[data-gstart]")) { $("#gEmpty").hidden = true; $("#gPrompt")?.focus(); $("#gPrompt")?.scrollIntoView({ block: "center", behavior: "smooth" }); return; }
  if (e.target.closest("[data-gclear]")) {
    $("#gGalStyle").value = ""; $("#gGalDate").value = "all"; $("#gGalProj").value = ""; gen.galStar = "all";
    $$("#gGalStar button").forEach((x) => x.classList.toggle("is-on", x.dataset.v === "all"));
    drawGallery(); return;
  }
  const b = e.target.closest(".gal-item"); if (!b) return;
  if ($("#gGal").classList.contains("selecting")) {
    gen.picked.has(b.dataset.name) ? gen.picked.delete(b.dataset.name) : gen.picked.add(b.dataset.name);
    b.classList.toggle("picked"); $("#gGalSelCount").textContent = `${gen.picked.size} selected`;
    return;
  }
  openLightbox(gen.gallery.indexOf(gen.view[Number(b.dataset.i)]));
});

$("#gGalActions")?.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const names = [...gen.picked];
  const act = b.dataset.act;
  if (act === "all") { gen.view.forEach((g) => gen.picked.add(g.name)); drawGallery(); return; }
  if (!names.length) return toast("Select some images first", "info");
  if (act === "star" || act === "unstar") { await api("/api/gen/star", { json: { names, on: act === "star" } }); toast(`${act === "star" ? "Starred" : "Unstarred"} ${names.length}`); }
  if (act === "export") { const r = await api("/api/gen/export", { json: { names } }); toast(`Exported ${r.count} to ${esc((r.folder || "").replace(/^\/Users\/[^/]+/, "~"))}`); return; }
  if (act === "fix") { const pick = await askFixes(b); if (pick) queueFixes(names, pick, galLabel); return; }
  if (act === "compare") {
    if (names.length < 2) return toast("Pick two or more images to compare", "info");
    if (names.length === 2) openCompare(names); else openCmpGrid(null, names);
    return;
  }
  if (act === "delete") { if (!(await confirmDialog(`Delete ${names.length} image${names.length > 1 ? "s" : ""}? This can't be undone.`))) return; await api("/api/gen/delete", { json: { names } }); gen.picked.clear(); toast(`Deleted ${names.length}`); }
  renderGallery();
});

export function tagComparison(jobs) {
  if (jobs.length < 2) return;
  const same = $("#gSameSeed").getAttribute("aria-pressed") === "true";
  const base = Number(jobs[0].params.seed);
  const seed = same ? (base >= 0 ? base : Math.floor(Math.random() * 2 ** 31)) : null;
  const id = `c${Date.now().toString(36)}`;
  for (const j of jobs) {
    j.params.compare = { id, n: jobs.length, seed };
    if (same) j.params.seed = seed;
  }
}

$("#gSameSeed")?.addEventListener("click", () => setToggle("#gSameSeed", $("#gSameSeed").getAttribute("aria-pressed") !== "true"));

export const cmpUi = { id: null, names: null, timer: null };
export const shortModel = (m) => (m || "").split(" [")[0].replace(/\.safetensors$/, "");
export function cmpColumn(p) { return p.style ? p.style.replace(/^Model · /, "") : shortModel(p.model) || "Manual"; }
export function cmpRow(p) { return p.pose_pack_id ? `pp:${p.pose_pack_id}` : p.pose_key ? `pk:${p.pose_key}` : ""; }
export function cmpRowHead(key) {
  if (!key) return `<span class="cmp-nopose">No pose</span>`;
  const src = key.startsWith("pp:") ? `/api/posepacks/thumb/${key.slice(3)}` : `/api/pose/skeleton/${key.slice(3)}`;
  return `<img src="${src}" alt="Pose" loading="lazy">`;
}

export function cmpTile(m) {
  const wrong = poseWrong(m), sc = m.pose_score;
  const badge = sc != null || wrong ? `<span class="cmp-score pose-${wrong ? "low" : poseClass(sc)}">${wrong ? "wrong way" : sc + "%"}</span>` : "";
  return `<button class="cmp-tile" data-name="${m.name}" title="${esc(cmpColumn(m.params || {}))} · seed ${esc(m.seed)}"><img src="/api/gen/thumb/${m.name}" alt="" loading="lazy">${badge}</button>`;
}

export async function openCmpGrid(id, names = null) {
  Object.assign(cmpUi, { id, names });
  $("#cmpGrid").hidden = false;
  await drawCmpGrid();
}

export async function drawCmpGrid() {
  clearTimeout(cmpUi.timer);
  if ($("#cmpGrid")?.hidden) return;
  let items, pending = [];
  if (cmpUi.id) ({ items, pending } = await api(`/api/gen/compare/${cmpUi.id}`).catch(() => ({ items: [], pending: [] })));
  else items = cmpUi.names.map((n) => gen.gallery.find((g) => g.name === n)).filter(Boolean);
  const all = [...items.map((m) => ({ m, p: m.params || {} })), ...pending.map((j) => ({ job: j, p: j.params }))];
  const cols = [...new Set(all.map((x) => cmpColumn(x.p)))], rows = [...new Set(all.map((x) => cmpRow(x.p)))];
  const cell = (c, r) => all.filter((x) => cmpColumn(x.p) === c && cmpRow(x.p) === r).map((x) => x.m ? cmpTile(x.m)
    : `<div class="cmp-tile cmp-wait"><i class="ph ${x.job.status === "running" ? "ph-spinner-gap" : "ph-hourglass"}"></i>${x.job.status === "running" ? "Generating" : "Waiting"}</div>`).join("");
  const showRows = rows.length > 1 || rows[0] !== "";
  $("#cmpGridBody").style.gridTemplateColumns = `${showRows ? "92px " : ""}repeat(${cols.length}, minmax(170px, 1fr))`;
  $("#cmpGridBody").innerHTML = (showRows ? `<div></div>` : "") + cols.map((c) => `<div class="cmp-col">${esc(c)}</div>`).join("")
    + rows.map((r) => (showRows ? `<div class="cmp-rowhead">${cmpRowHead(r)}</div>` : "") + cols.map((c) => `<div class="cmp-cell">${cell(c, r)}</div>`).join("")).join("");
  const seeds = [...new Set(items.map((m) => m.seed))];
  const scored = items.filter((m) => m.pose_score != null);
  $("#cmpGridNote").textContent = [`${items.length} image${items.length !== 1 ? "s" : ""}`, pending.length ? `${pending.length} job${pending.length > 1 ? "s" : ""} to go` : "",
    `${cols.length} × ${rows.length}`, seeds.length === 1 && items.length > 1 ? `same seed ${seeds[0]}` : "",
    scored.length ? `pose avg ${Math.round(scored.reduce((n, m) => n + m.pose_score, 0) / scored.length)}%` : ""].filter(Boolean).join(" · ");
  if (pending.length) cmpUi.timer = setTimeout(drawCmpGrid, 8000);
}

$("#cmpGridClose")?.addEventListener("click", () => { $("#cmpGrid").hidden = true; clearTimeout(cmpUi.timer); });
$("#cmpGrid")?.addEventListener("click", async (e) => {
  const t = e.target.closest(".cmp-tile[data-name]"); if (!t) return;
  let i = gen.gallery.findIndex((g) => g.name === t.dataset.name);
  if (i < 0) { await renderGallery(); i = gen.gallery.findIndex((g) => g.name === t.dataset.name); }
  if (i >= 0) openLightbox(i);
});

export function openCompare(names) {
  const items = names.map((n) => gen.gallery.find((g) => g.name === n)).filter(Boolean);
  $("#cmpPanes").innerHTML = items.map((g) => {
    const p = g.params || {};
    return `<div class="cmp-pane"><img src="/api/gen/image/${g.name}" alt=""><p><b>${esc(p.style || "No style")}</b> · seed ${esc(g.seed)} · ${esc(p.sampler || "")} ${esc(p.steps || "")} steps · CFG ${esc(p.cfg || "")}<br>${esc((p.prompt || "").slice(0, 220))}</p></div>`;
  }).join("");
  $("#compare").hidden = false;
}

$("#cmpClose")?.addEventListener("click", () => { $("#compare").hidden = true; });
$("#gPreview")?.addEventListener("click", () => { if (!gen.polling && gen.gallery.length) openLightbox(0); });

export function sendToGenerate(p, what) {
  showView("generate");
  applyParams(p);
  if (!gen.opts?.online) gen.pending = p;
  toast(`${esc(what)} loaded into Generate`, "info");
}

export async function openInGenerate(id, promptOverride) {
  try {
    const p = await api(`/api/record/${id}/gen`);
    if (promptOverride) Object.assign(p, promptOverride);
    sendToGenerate({ ...p, seed: -1 }, `#${id}`);
  } catch (e) { toast(esc(e.message), "err"); }
}

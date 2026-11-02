// standalone/web/src/components/lightbox.js
// Full-screen image viewer, zoom/pan controller, filmstrip, and image actions.

import { $, api, esc, fmt, toast, copyText, confirmDialog } from "../api.js";
import { state, gen } from "../state.js";
import { showView } from "../main.js";
import { poseClass } from "./pose-browser.js";
import {
  poseWrong, applyParams, runGen, startPolling, setRemix,
  renderGallery, openCmpGrid, numOf,
} from "../views/generate.js";
import { pickImage } from "../views/interrogate.js";

export function renderLbStrip() {
  const strip = $("#lbStrip");
  if (!strip) return;
  if ($("#lightbox").classList.contains("viewer") || gen.gallery.length <= 1) {
    strip.hidden = true;
    return;
  }
  const sig = gen.gallery.map((g) => g.name).join(",") + "|" + gen.lb;
  if (sig === renderLbStrip.sig) {
    if (!$("#lightbox").hidden) strip.hidden = false;
    return;
  }
  renderLbStrip.sig = sig;
  strip.hidden = false;
  strip.innerHTML = gen.gallery.map((g, idx) => `
    <img class="lb-strip-thumb${idx === gen.lb ? " is-on" : ""}" data-i="${idx}" src="/api/gen/thumb/${esc(g.name)}" title="Seed ${esc(g.seed)}" alt="">
  `).join("");
  const cur = strip.querySelector(".lb-strip-thumb.is-on");
  cur?.scrollIntoView({ inline: "center", block: "nearest", behavior: "auto" });
}

$("#lbStrip")?.addEventListener("click", (e) => {
  const t = e.target.closest(".lb-strip-thumb[data-i]");
  if (t) openLightbox(Number(t.dataset.i));
});

export function openLightbox(i) {
  $("#lightbox").classList.remove("viewer");
  gen.lb = i;
  const g = gen.gallery[i]; if (!g) return;
  if (gen.fresh.delete(g.name)) {
    const tile = $(`.gal-item[data-name="${g.name}"]`);
    tile?.classList.remove("fresh", "arriving"); tile?.querySelector(".gal-new")?.remove();
  }
  zoom.reset();
  $("#lbImg").src = `/api/gen/image/${g.name}`;
  const p = g.params || {};
  $("#lbMeta").innerHTML = `<b>Seed ${esc(g.seed)}</b>${p.style ? ` · ${esc(p.style)}` : ""}${p.variation ? " · variation" : ""} · ${esc(p.width)}×${esc(p.height)} · ${esc(p.sampler)} · ${esc(p.steps)} steps · CFG ${esc(p.cfg)}${p.hires ? ` · hires ×${esc(p.hr_scale)}` : ""}${g.pose_score != null || poseWrong(g) ? ` · <span class="pose-${poseWrong(g) ? "low" : poseClass(g.pose_score)}">pose ${g.pose_score != null ? esc(g.pose_score) + "%" : ""}${g.pose_facing && g.pose_facing !== "ok" ? ` (${esc(g.pose_facing)})` : ""}</span>` : ""}`;
  $("#lbCmp").hidden = !p.compare;
  $("#lightbox").hidden = false;
  $("#lbStar").classList.toggle("is-on", !!g.starred);
  $("#lbStar i").className = g.starred ? "ph-fill ph-star" : "ph ph-star";
  renderLbStrip();
}

export function closeLightbox() {
  $("#lightbox").hidden = true;
  $("#lbStrip").hidden = true;
  zoom.reset();
}

export function lbStep(d) {
  if ($("#lightbox").classList.contains("viewer")) return;
  if (gen.gallery.length) openLightbox((gen.lb + d + gen.gallery.length) % gen.gallery.length);
}

$("#lbClose")?.addEventListener("click", closeLightbox);
$("#lbPrev")?.addEventListener("click", () => lbStep(-1));
$("#lbNext")?.addEventListener("click", () => lbStep(1));
$("#lightbox")?.addEventListener("click", (e) => { if (e.target.id === "lightbox") closeLightbox(); });

export const zoom = (() => {
  const stage = $("#lbStage"), img = $("#lbImg");
  const z = { s: 1, tx: 0, ty: 0, drag: null, moved: false };
  const MAX = 16;
  const actual = () => (img?.naturalWidth && img?.offsetWidth ? img.naturalWidth / img.offsetWidth : 1);
  function clamp() {
    const sw = stage.clientWidth, sh = stage.clientHeight;
    const w = img.offsetWidth * z.s, h = img.offsetHeight * z.s, L = img.offsetLeft, T = img.offsetTop;
    z.tx = w <= sw ? (sw - w) / 2 - L : Math.min(-L, Math.max(sw - w - L, z.tx));
    z.ty = h <= sh ? (sh - h) / 2 - T : Math.min(-T, Math.max(sh - h - T, z.ty));
  }
  function apply(animate = false) {
    if (z.s <= 1.001) { z.s = 1; z.tx = 0; z.ty = 0; } else clamp();
    stage.classList.toggle("animate", animate);
    img.style.transform = z.s === 1 ? "" : `translate(${z.tx}px, ${z.ty}px) scale(${z.s})`;
    stage.classList.toggle("zoomed", z.s > 1);
    stage.classList.toggle("pixel", z.s * img.offsetWidth / (img.naturalWidth || 1) >= 3);
    const pct = Math.round((z.s / actual()) * 100);
    $("#lbZoomPct").textContent = z.s === 1 ? `Fit · ${pct}%` : `${pct}%`;
  }
  function to(next, px, py, animate = false) {
    next = Math.max(1, Math.min(MAX * Math.max(1, actual()), next));
    if (px === undefined) { px = stage.clientWidth / 2; py = stage.clientHeight / 2; }
    const L = img.offsetLeft, T = img.offsetTop;
    const ux = (px - L - z.tx) / z.s, uy = (py - T - z.ty) / z.s;
    z.tx = px - L - next * ux; z.ty = py - T - next * uy; z.s = next;
    apply(animate);
  }
  const at = (e) => { const r = stage.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  stage?.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (!e.ctrlKey && !e.metaKey && z.s > 1) { z.tx -= e.deltaX; z.ty -= e.deltaY; apply(); return; }
    const k = e.ctrlKey ? 0.01 : 0.0018;
    to(z.s * Math.exp(-e.deltaY * k), ...at(e));
  }, { passive: false });
  stage?.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    z.moved = false;
    if (z.s > 1) { z.drag = { x: e.clientX, y: e.clientY, tx: z.tx, ty: z.ty }; stage.setPointerCapture(e.pointerId); stage.classList.add("panning"); }
  });
  stage?.addEventListener("pointermove", (e) => {
    if (!z.drag) return;
    const dx = e.clientX - z.drag.x, dy = e.clientY - z.drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) z.moved = true;
    z.tx = z.drag.tx + dx; z.ty = z.drag.ty + dy; apply();
  });
  const end = () => { z.drag = null; stage?.classList.remove("panning"); };
  stage?.addEventListener("pointerup", end); stage?.addEventListener("pointercancel", end);
  stage?.addEventListener("dblclick", (e) => { z.s > 1 ? to(1, ...at(e), true) : to(Math.max(2, actual()), ...at(e), true); });
  stage?.addEventListener("click", (e) => { if (!z.moved && z.s === 1 && e.target === stage) closeLightbox(); });
  img?.addEventListener("load", () => { z.s = 1; apply(); });
  window.addEventListener("resize", () => { if (!$("#lightbox")?.hidden) apply(); });
  $("#lbZoomIn")?.addEventListener("click", () => to(z.s * 1.5, undefined, undefined, true));
  $("#lbZoomOut")?.addEventListener("click", () => to(z.s / 1.5, undefined, undefined, true));
  $("#lbZoomPct")?.addEventListener("click", () => to(1, undefined, undefined, true));
  $("#lbZoom1")?.addEventListener("click", () => to(actual(), undefined, undefined, true));
  return {
    reset() { z.s = 1; z.tx = z.ty = 0; z.drag = null; apply(); },
    key(e) {
      const k = e.key;
      if (k === "+" || k === "=") to(z.s * 1.5, undefined, undefined, true);
      else if (k === "-" || k === "_") to(z.s / 1.5, undefined, undefined, true);
      else if (k === "0") to(1, undefined, undefined, true);
      else if (k === "1") to(actual(), undefined, undefined, true);
      else if (z.s > 1 && k.startsWith("Arrow")) {
        const d = 80; z.tx += k === "ArrowLeft" ? d : k === "ArrowRight" ? -d : 0; z.ty += k === "ArrowUp" ? d : k === "ArrowDown" ? -d : 0; apply(true);
      } else return false;
      return true;
    },
  };
})();

export function askFixes(anchor) {
  return new Promise((resolve) => {
    document.querySelector(".fix-menu")?.remove();
    const on = (id) => $(id)?.getAttribute("aria-pressed") === "true";
    const pre = { body: on("#gFixBody"), face: on("#gFixFace"), hands: on("#gFixHands") };
    if (!pre.body && !pre.face && !pre.hands) Object.assign(pre, { face: true, hands: true });
    const m = document.createElement("div");
    m.className = "fix-menu"; m.setAttribute("role", "dialog"); m.setAttribute("aria-label", "Fixes");
    m.innerHTML = `<b>Fix this image</b>
      ${[["body", "Body", "ph-person", "whole figure, gentle (0.35)"], ["face", "Face", "ph-smiley", ""], ["hands", "Hands", "ph-hand", ""]]
        .map(([k, l, ic, hint]) => `<label><input type="checkbox" data-k="${k}" ${pre[k] ? "checked" : ""}><i class="ph ${ic}"></i>${l}${hint ? `<span class="muted small">${hint}</span>` : ""}</label>`).join("")}
      <div class="fix-menu-row"><button class="btn btn-sm" data-x="cancel">Cancel</button><button class="btn btn-sm btn-primary" data-x="go">Run fixes</button></div>`;
    document.body.append(m);
    const r = anchor.getBoundingClientRect();
    m.style.left = `${Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8))}px`;
    m.style.top = `${r.top - m.offsetHeight - 8 > 8 ? r.top - m.offsetHeight - 8 : r.bottom + 8}px`;
    const done = (v) => { m.remove(); document.removeEventListener("keydown", esc_, true); resolve(v); };
    const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(null); } };
    document.addEventListener("keydown", esc_, true);
    m.addEventListener("click", (e) => {
      const x = e.target.closest("[data-x]"); if (!x) return;
      if (x.dataset.x === "cancel") return done(null);
      const pick = Object.fromEntries([...m.querySelectorAll("[data-k]")].map((c) => [c.dataset.k, c.checked]));
      if (!pick.body && !pick.face && !pick.hands) return toast("Pick at least one fix", "err");
      done(pick);
    });
    m.querySelector('[data-x="go"]')?.focus();
  });
}

export async function queueFixes(names, pick, labelOf) {
  const what = ["body", "face", "hands"].filter((k) => pick[k]);
  const jobs = names.map((n) => ({
    params: { mode: "fix", source: n, fix_body: pick.body, fix_face: pick.face, fix_hands: pick.hands, count: 1 },
    label: `Fix ${what.join(" + ")} · ${labelOf(n)}`,
  }));
  await api("/api/gen/run", { json: { jobs } });
  toast(`Fixing ${what.join(", ")} on ${names.length} image${names.length !== 1 ? "s" : ""} (new copies, originals kept)`, "info");
  startPolling();
}

export const galLabel = (n) => { const g = gen.gallery.find((x) => x.name === n); return (g?.label || g?.params?.prompt || "").slice(0, 50); };

$("#lbSeed")?.addEventListener("click", () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  applyParams({ ...g.params, seed: g.seed, count: 1 });
  closeLightbox();
  toast(`Loaded seed ${g.seed}`, "info");
});

$("#lbKritaDoc")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  const r = await api("/api/krita/open", { json: { gen_name: g.name } }).catch((e) => ({ ok: false, error: e.message }));
  r.ok ? toast(`Opened in Krita (${r.size?.join("×")})`) : toast(esc(r.error), "err");
});

$("#lbFix")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  const pick = await askFixes($("#lbFix")); if (!pick) return;
  closeLightbox(); queueFixes([g.name], pick, galLabel);
});

$("#lbUpscale")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  const p = {
    mode: "upscale", source: g.name, scale: Math.max(1.25, numOf("#gHrScale")), upscaler: $("#gHrUp").value, denoise: Math.min(0.45, numOf("#gHrDen")),
    fix_face: $("#gFixFace").getAttribute("aria-pressed") === "true", fix_hands: $("#gFixHands").getAttribute("aria-pressed") === "true", fix_body: $("#gFixBody").getAttribute("aria-pressed") === "true", count: 1,
  };
  await api("/api/gen/run", { json: { jobs: [{ params: p, label: `Upscale ×${p.scale} · ${(g.label || g.params?.prompt || "").slice(0, 50)}` }] } });
  closeLightbox(); toast(`Upscaling ×${p.scale} queued`, "info"); startPolling();
});

$("#lbRemix")?.addEventListener("click", () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  const im = $("#lbImg");
  setRemix({ name: g.name, width: im.naturalWidth - (im.naturalWidth % 8), height: im.naturalHeight - (im.naturalHeight % 8) });
  closeLightbox(); toast("Remixing from this image. Pick a style or edit the prompt, then Generate.", "info");
});

$("#lbVary")?.addEventListener("click", () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  applyParams({ ...g.params, seed: g.seed, count: 4 });
  gen.variation = true;
  closeLightbox(); runGen();
});

$("#lbCopy")?.addEventListener("click", () => {
  const g = gen.gallery[gen.lb];
  if (g) copyText(g.final_prompt || g.params?.prompt || "");
});

$("#lbReveal")?.addEventListener("click", () => {
  const g = gen.gallery[gen.lb];
  if (g) api("/api/gen/reveal", { json: { name: g.name } });
});

$("#lbDelete")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  if (!(await confirmDialog("Delete this image?"))) return;
  await api("/api/gen/delete", { json: { name: g.name } });
  closeLightbox(); renderGallery();
});

$("#lbInterrogate")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  const blob = await fetch(`/api/gen/image/${g.name}`).then((r) => r.blob());
  closeLightbox(); showView("interrogate");
  pickImage(new File([blob], g.name, { type: "image/png" }));
});

$("#lbKrita")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  try {
    const r = await api("/api/krita/prompt", { json: { prompt: g.params?.prompt || "", negative: "", style: "" } });
    if (!r.ok) return toast(esc(r.error), "err");
    const im = await api("/api/krita/image", { json: { gen_name: g.name, modes: ["reference"] } });
    im.ok ? toast("Sent to Krita: prompt + image as reference") : toast(`Prompt sent, image wasn't: ${esc(im.error)}`, "err");
  } catch (e) { toast(esc(e.message), "err"); }
});

$("#lbStar")?.addEventListener("click", async () => {
  const g = gen.gallery[gen.lb];
  if (!g) return;
  g.starred = !g.starred;
  await api("/api/gen/star", { json: { names: [g.name], on: g.starred } });
  $("#lbStar").classList.toggle("is-on", g.starred);
  $("#lbStar i").className = g.starred ? "ph-fill ph-star" : "ph ph-star";
  renderGallery();
  renderLbStrip();
});

$("#lbCmp")?.addEventListener("click", () => {
  const c = gen.gallery[gen.lb]?.params?.compare;
  if (c) { closeLightbox(); openCmpGrid(c.id); }
});

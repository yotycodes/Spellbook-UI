// standalone/web/src/components/pose-browser.js
// Pose browser component: inspector, Generate, and full-screen modal.

import { $, api, esc, fmt, toast, confirmDialog } from "../api.js";
import { state, savePrefs, gen, activePoseBrowsers } from "../state.js";
import { showView } from "../main.js";
import { openLightbox } from "./lightbox.js";
import { poseBatchApi, renderGallery } from "../views/generate.js";

export const POSE_SHOW = [["", "All"], ["starred", "★ Starred"], ["worked", "✓ Worked"], ["refs", "80%+ refs"], ["recent", "Recent"]];
export const POSE_SOURCES = [
  ["", "All sources"], ["fashion", "Fashion packs"], ["dynamic", "Dynamic packs"], ["nsfw", "NSFW packs"],
  ["kit", "My Pose Kit"], ["mine", "From my images"],
];

export { activePoseBrowsers };

export function syncBrowserFilters(src, dst) {
  if (!src?.st || !dst?.st) return;
  dst.st.q = src.st.q || "";
  dst.st.cat = src.st.cat || "";
  dst.st.pack = src.st.pack || "";
  dst.st.tags = [...(src.st.tags || [])];
  dst.st.show = src.st.show || "";
  dst.st.similarOf = src.st.similarOf || null;
}

export const poseClass = (v) => (v >= 75 ? "ok" : v >= 50 ? "mid" : "low");

export function poseQuality(x) {
  const r = x.rec;
  if (r && (r.avg != null || r.wrong)) {
    const bad = r.wrong * 2 >= r.n, cls = bad ? "low" : poseClass(r.avg ?? 0);
    return `<span class="pp-q ${cls}">${bad ? '<i class="ph ph-arrows-counter-clockwise"></i>' : '<i class="ph ph-check"></i>'}${r.avg != null ? r.avg + "%" : ""}</span>`;
  }
  return x.q === "unclear" ? `<span class="pp-q unclear"><i class="ph ph-question"></i></span>` : "";
}

export function poseQualityText(x) {
  const r = x.rec, lines = [];
  if (r) lines.push(`Used ${r.n}×${r.avg != null ? ` · average match ${r.avg}%` : ""}${r.wrong ? ` · ${r.wrong} wrong way` : ""}`);
  if (x.q === "unclear") lines.push(`Unclear skeleton: ${x.qwhy}. Pose check and the facing filter can't judge it well.`);
  else if (x.q === "partial") lines.push(`Partly readable: ${x.qwhy}.`);
  return lines.length ? "\n" + esc(lines.join("\n")) : "";
}

export function showPoseRefs(x, onChange) {
  document.querySelector(".refs-overlay")?.remove();
  const o = document.createElement("div");
  o.className = "refs-overlay"; o.setAttribute("role", "dialog"); o.setAttribute("aria-label", "Pose results");
  const draw = () => {
    const refs = x.rec?.refs || [];
    o.innerHTML = `<div class="refs-box"><div class="refs-head"><b>${esc(x.label)}</b><span class="muted">${refs.length} result${refs.length !== 1 ? "s" : ""} at 80%+ · ${esc(x.pack)}</span>
        <button class="icon-btn" data-x="close" aria-label="Close"><i class="ph ph-x"></i></button></div>
      <div class="refs-row"><figure><img src="/api/posepacks/image/${x.id}" alt=""><figcaption>Skeleton</figcaption></figure>
        ${refs.map((r) => `<figure><img src="/api/posepacks/ref/${x.id}/${r.file}" alt="">
          <figcaption>${r.score ?? ""}% match · ${r.in_gallery ? `<button class="linkbtn" data-open="${r.source}">Open in gallery</button>` : `<span class="muted">not in gallery</span>`}
          · <button class="linkbtn" data-remove="${r.file}">Remove ref</button></figcaption></figure>`).join("")}</div></div>`;
  };
  draw();
  document.body.append(o);
  const close = () => { o.remove(); document.removeEventListener("keydown", k, true); };
  const k = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", k, true);
  o.addEventListener("click", async (e) => {
    if (e.target === o || e.target.closest('[data-x="close"]')) return close();
    const rm = e.target.closest("[data-remove]");
    if (rm) {
      if (!(await confirmDialog("Remove this picture from the pose's refs? It won't be added back."))) return;
      const r = await api("/api/posepacks/ref/remove", { json: { pid: x.id, file: rm.dataset.remove } }).catch((er) => (toast(esc(er.message), "err"), null));
      if (!r) return;
      x.rec.refs = r.refs; onChange?.();
      for (const b of activePoseBrowsers) {
        const item = b.st.items.find((i) => i.id === x.id);
        if (item) {
          if (!item.rec) item.rec = {};
          item.rec.refs = r.refs;
          b.draw();
        }
      }
      if (!r.refs.length) return close();
      draw(); return;
    }
    const op = e.target.closest("[data-open]");
    if (op) {
      close(); document.querySelector("#poseModal:not([hidden]) #poseModalClose")?.click();
      showView("generate"); if (!gen.gallery?.length) await renderGallery();
      const i = gen.gallery.findIndex((g) => g.name === op.dataset.open); if (i >= 0) openLightbox(i);
    }
  });
}

export function showPosePreview(x, tile) {
  hidePosePreview();
  const refs = (x.rec?.refs || []).slice(0, 3);
  const p = document.createElement("div");
  p.className = "pose-preview"; p.setAttribute("aria-hidden", "true");
  p.innerHTML = `<div class="pp-row">
      <figure><img src="/api/posepacks/image/${x.id}" alt=""><figcaption>Skeleton</figcaption></figure>
      ${refs.map((r) => `<figure><img src="/api/posepacks/ref/${x.id}/${r.file}" alt=""><figcaption>${r.score ?? ""}% match</figcaption></figure>`).join("")}
    </div>
    <div class="pp-info"><b>${esc(x.label)}</b><span>${esc(x.pack)}</span>${x.tags.length ? `<span class="muted">${esc(x.tags.join(" · "))}</span>` : ""}
      ${x.q === "unclear" ? `<span class="pp-warn">Unclear skeleton: ${esc(x.qwhy || "")}</span>` : ""}</div>`;
  document.body.append(p);
  const place = () => {
    const r = tile.getBoundingClientRect(), w = p.offsetWidth, h = p.offsetHeight, m = 12;
    let left = r.right + m;
    if (left + w > innerWidth - 8) left = r.left - w - m;          // no room on the right: go left of the tile
    if (left < 8) left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    let top = Math.max(8, Math.min(innerHeight - h - 8, r.top + r.height / 2 - h / 2));
    if (left < r.right && left + w > r.left) top = r.top - h - m > 8 ? r.top - h - m : r.bottom + m;   // centred: above/below
    p.style.left = `${left}px`; p.style.top = `${top}px`;
  };
  place();
  p.querySelectorAll("img").forEach((im) => im.addEventListener("load", place, { once: true }));
}

export function hidePosePreview() { document.querySelectorAll(".pose-preview").forEach((n) => n.remove()); }

export function packBrowser(root, onPick, getSelected, opts = {}) {
  const st = { show: "", cat: "", pack: "", q: "", tags: [], page: 0, items: [], pages: 1, total: 0, packs: [], counts: [], filters: [], similarOf: null };
  const per = opts.big ? 96 : 60;
  const inst = { load, draw, st, root, loaded: false };
  activePoseBrowsers.add(inst);

  async function load(reset = true) {
    inst.loaded = true;
    if (reset) { st.page = 0; st.items = []; st.scrollReset = true; }
    const rating = state.poseRating;
    if (rating === "SFW" && st.cat === "nsfw") st.cat = "";
    const r = st.similarOf
      ? await api(`/api/posepacks/similar/${st.similarOf.id}?rating=${rating}&limit=90`).catch((e) => (toast(esc(e.message), "err"), { of: st.similarOf, items: [] }))
      : await api(`/api/posepacks?${new URLSearchParams({ cat: st.show || st.cat, pack: st.pack, q: st.q, tags: st.tags.join(","), page: st.page, per, rating,
        clear: !!state.poseClearOnly, depth: !!state.poseDepthOnly })}`);
    if (st.similarOf) { st.items = r.items; st.total = r.items.length; st.pages = 1; }
    else { st.packs = r.packs; st.counts = r.tag_counts; st.filters = r.filters || []; st.items = st.items.concat(r.items); st.pages = r.pages; st.total = r.total; }
    draw();
  }

  const batchNo = (x) => opts.batch ? opts.batch.index(x.id) + 1 : 0;   // 1-based place in the multi-pose batch, 0 = not in it

  function tile(x, sel) {
    return `<div class="pack-pose-wrap"><button class="pack-pose${x.id === sel ? " is-on" : ""}${batchNo(x) ? " in-batch" : ""}${x.q === "unclear" ? " pp-unclear" : ""}" data-id="${x.id}" title="${esc(x.pack)} · ${esc(x.label)}${x.tags.length ? "\n" + esc(x.tags.join(", ")) : ""}${poseQualityText(x)}">${x.rec?.refs?.length ? `<img loading="lazy" class="pp-refimg" src="/api/posepacks/refthumb/${x.id}/${x.rec.refs[0].file}" alt=""><img loading="lazy" class="pp-skel" src="/api/posepacks/thumb/${x.id}" alt="">` : `<img loading="lazy" src="/api/posepacks/thumb/${x.id}" alt="">`}${poseQuality(x)}${x.depth ? `<span class="pp-depth" title="Has a depth map">D</span>` : ""}${x.tags.includes("from behind") ? `<span class="pp-back" title="Back view">Back</span>` : ""}${batchNo(x) ? `<span class="pp-batch" title="In the batch: one job per pose">${batchNo(x)}</span>` : ""}</button>
      <button class="pp-act pp-star${x.star ? " on" : ""}" data-star="${x.id}" aria-label="${x.star ? "Unstar" : "Star"} pose" title="${x.star ? "Unstar" : "Star"}"><i class="${x.star ? "ph-fill" : "ph"} ph-star"></i></button>
      ${x.rec?.refs?.length ? `<button class="pp-act pp-refs" data-refs="${x.id}" aria-label="See this pose's best results" title="${x.rec.refs.length} result${x.rec.refs.length > 1 ? "s" : ""} that matched this pose 80% or better (best: ${x.rec.refs[0].score ?? ""}%)"><i class="ph ph-images"></i>${x.rec.refs.length > 1 ? x.rec.refs.length : ""}</button>` : ""}
      <button class="pp-act pp-sim" data-sim="${x.id}" aria-label="Find similar poses" title="Find similar poses"><i class="ph ph-intersect"></i></button>
      <button class="pp-act pp-nsfw${x.nsfw ? " on" : ""}" data-nsfw="${x.id}" aria-label="${x.nsfw ? "Mark as safe" : "Mark as NSFW"}" title="${x.nsfw ? "NSFW · click to mark safe" : "Mark as NSFW"}">${x.nsfw ? "18+" : '<i class="ph ph-eye-slash"></i>'}</button></div>`;
  }

  function draw() {
    const grid = root.querySelector(".pack-grid");
    const keep = st.scrollReset ? 0 : grid?.scrollTop || 0, keepRoot = st.scrollReset ? 0 : root.scrollTop;
    st.scrollReset = false;
    drawGrid();
    const g = root.querySelector(".pack-grid");
    if (g) g.scrollTop = keep;
    root.scrollTop = keepRoot;
  }

  function drawGrid() {
    const sel = getSelected();
    const sources = POSE_SOURCES.filter(([v]) => v !== "nsfw" || state.poseRating !== "SFW");
    const ratingSeg = `<div class="seg pose-rating" data-role="rating" role="group" aria-label="Pose rating">${[["SFW", "SFW"], ["All", "All"], ["NSFW", "NSFW"]]
      .map(([v, l]) => `<button data-r="${v}" class="${state.poseRating === v ? "is-on" : ""}" aria-pressed="${state.poseRating === v}">${l}</button>`).join("")}</div>`;
    const packs = st.packs.filter((p) => !st.cat || p.cat === st.cat);
    const srcVal = st.pack ? `pack:${st.pack}` : st.cat ? `cat:${st.cat}` : "";
    const active = st.tags.length + !!st.q + !!st.cat + !!st.pack + !!st.show + !!state.poseDepthOnly + !!state.poseClearOnly;
    root.innerHTML = st.similarOf ? `
      <div class="pack-similar"><button class="btn btn-sm" data-role="back"><i class="ph ph-arrow-left"></i>Back</button>
        <img src="/api/posepacks/thumb/${st.similarOf.id}" alt=""><span>Closest ${st.items.length} poses to this one</span></div>
      <div class="pack-grid">${st.items.map((x) => tile(x, sel)).join("") || `<p class="muted">No similar poses found.</p>`}</div>` : `
      <div class="pack-bar">
        <input class="input" data-role="q" placeholder="Search poses, e.g. hero landing…" value="${esc(st.q)}" autocomplete="off" spellcheck="false" aria-label="Search poses">
        <button class="btn btn-sm" data-role="fromimg" title="Extract the pose from an image with Forge (DWPose)"><i class="ph ph-image-square"></i>From image…</button>
        ${opts.big ? "" : `<button class="icon-btn" data-role="expand" aria-label="Open the full pose browser" title="Open the full pose browser"><i class="ph ph-arrows-out-simple"></i></button>`}
      </div>
      <div class="pack-bar">
        <div class="seg" data-role="show" role="group" aria-label="Show">${POSE_SHOW.map(([v, l]) => `<button data-v="${v}" class="${v === st.show ? "is-on" : ""}" aria-pressed="${v === st.show}">${l}</button>`).join("")}</div>
        <select class="input" data-role="source" aria-label="Pose source">
          ${sources.map(([v, l]) => `<option value="${v ? `cat:${v}` : ""}" ${srcVal === (v ? `cat:${v}` : "") ? "selected" : ""}>${l}</option>`).join("")}
          ${packs.length ? `<optgroup label="Packs">${packs.map((p) => `<option value="pack:${esc(p.name)}" ${srcVal === `pack:${p.name}` ? "selected" : ""}>${esc(p.name)} (${fmt(p.count)})</option>`).join("")}</optgroup>` : ""}
        </select>
      </div>
      <div class="pose-filters">${st.filters.map((f) => `<label class="pf${f.selected ? " is-on" : ""}"><span>${f.name}</span>
        <select class="input" data-group="${f.name}" aria-label="${f.name}"><option value="">Any</option>${f.options.filter(([o, n]) => n || o === f.selected)
          .map(([o, n]) => `<option value="${esc(o)}" ${o === f.selected ? "selected" : ""}>${esc(o)} · ${fmt(n)}</option>`).join("")}</select></label>`).join("")}</div>
      <div class="pack-bar">
        <button class="toggle toggle-sm${state.poseDepthOnly ? " is-on" : ""}" data-role="depthonly" aria-pressed="${!!state.poseDepthOnly}" title="Only poses with a depth map (D): best results for sitting, lying, leaning and back poses"><i class="ph ph-cube"></i>Has depth</button>
        <button class="toggle toggle-sm${state.poseClearOnly ? " is-on" : ""}" data-role="clearonly" aria-pressed="${!!state.poseClearOnly}" title="Hide skeletons Spellbook can't read well (marked ?)"><i class="ph ph-funnel"></i>Hide unclear</button>
        ${ratingSeg}
        ${opts.batch ? `<button class="toggle toggle-sm${opts.batch.mode() ? " is-on" : ""}" data-role="batchmode" aria-pressed="${opts.batch.mode()}" title="Pick several poses: Generate makes one job per pose (also ⌘-click or Shift-click a pose)"><i class="ph ph-stack"></i>Batch${opts.batch.size() ? ` · ${opts.batch.size()}` : ""}</button>` : ""}
      </div>
      <div class="pack-count"><span>${fmt(st.total)} poses${state.poseRating === "SFW" ? " · NSFW hidden" : state.poseRating === "NSFW" ? " · NSFW only" : ""}</span>
        ${active ? `<button class="linkbtn" data-role="clearall"><i class="ph ph-x"></i>Clear filters</button>` : ""}</div>
      <div class="pack-grid">${st.items.map((x) => tile(x, sel)).join("") || `<p class="muted">${st.show === "worked" ? "Poses that scored 70%+ the right way round in your renders show up here. Keep Pose check on." : st.show === "starred" ? "Star poses to keep them here." : st.show === "recent" ? "Poses you use show up here." : st.cat === "mine" ? "Use “From image…” to extract a pose from any image." : "No poses match. Set a filter back to Any, or Clear filters."}</p>`}</div>
      ${st.page + 1 < st.pages ? `<button class="btn btn-sm pack-more" data-role="more">Load more</button>` : ""}`;
  }

  let hoverT;
  root.addEventListener("mouseover", (e) => {
    const t = e.target.closest(".pack-pose"); if (!t || t === root._hoverTile) return;
    root._hoverTile = t; clearTimeout(hoverT);
    hoverT = setTimeout(() => { const x = st.items.find((i) => i.id === t.dataset.id); if (x && t.isConnected) showPosePreview(x, t); }, 320);
  });
  root.addEventListener("mouseout", (e) => {
    const t = e.target.closest(".pack-pose"); if (!t || t.contains(e.relatedTarget)) return;
    root._hoverTile = null; clearTimeout(hoverT); hidePosePreview();
  });
  root.addEventListener("scroll", () => { clearTimeout(hoverT); hidePosePreview(); }, true);
  root.addEventListener("mousedown", () => { clearTimeout(hoverT); hidePosePreview(); });

  const fileIn = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", hidden: true });
  root.after(fileIn);
  fileIn.addEventListener("change", async () => {
    const f = fileIn.files[0]; fileIn.value = ""; if (!f) return;
    toast("Reading the pose with Forge…", "info");
    try {
      const up = await fetch("/api/gen/input", { method: "POST", body: f }).then((x) => x.json());
      const r = await api("/api/pose/detect", { json: { input_name: up.name } });
      st.cat = "mine"; st.similarOf = null; await load();
      onPick(r.pose); draw();
      toast(`Pose extracted${r.people > 1 ? ` (${r.people} people found, using the first)` : ""}: ${esc(r.pose.tags.join(", ") || "no clear tags")}`);
    } catch (e) { toast(esc(e.message), "err"); }
  });

  root.addEventListener("click", async (e) => {
    const sh = e.target.closest('[data-role="show"] [data-v]'); if (sh) { st.show = sh.dataset.v; load(); return; }
    if (e.target.closest('[data-role="depthonly"]')) { state.poseDepthOnly = !state.poseDepthOnly; savePrefs(); for (const b of activePoseBrowsers) b.load(); return; }
    if (e.target.closest('[data-role="clearall"]')) {
      Object.assign(st, { show: "", cat: "", pack: "", q: "", tags: [] }); state.poseDepthOnly = false; state.poseClearOnly = false; savePrefs(); load(); return;
    }
    if (e.target.closest('[data-role="batchmode"]')) { opts.batch?.setMode(!opts.batch.mode()); draw(); return; }
    if (e.target.closest('[data-role="clearonly"]')) { state.poseClearOnly = !state.poseClearOnly; savePrefs(); for (const b of activePoseBrowsers) b.load(); return; }
    const rt = e.target.closest('[data-role="rating"] [data-r]');
    if (rt) { state.poseRating = rt.dataset.r; savePrefs(); for (const b of activePoseBrowsers) { b.st.pack = ""; b.load(); } return; }
    const rb = e.target.closest("[data-refs]");
    if (rb) { const x = st.items.find((i) => i.id === rb.dataset.refs); if (x) showPoseRefs(x, draw); return; }
    const nb = e.target.closest("[data-nsfw]");
    if (nb) {
      const x = st.items.find((i) => i.id === nb.dataset.nsfw);
      if (!x) return;
      x.nsfw = !x.nsfw;
      await api("/api/posepacks/nsfw", { json: { id: x.id, on: x.nsfw } });
      toast(x.nsfw ? "Marked NSFW" : "Marked safe", "info");
      for (const b of activePoseBrowsers) {
        const it = b.st.items.find((i) => i.id === x.id);
        if (it) {
          it.nsfw = x.nsfw;
          if ((state.poseRating === "SFW" && x.nsfw) || (state.poseRating === "NSFW" && !x.nsfw)) b.st.items = b.st.items.filter((i) => i !== it);
          b.draw();
        }
      }
      return;
    }
    const tg = e.target.closest("[data-tag]"); if (tg) { const t = tg.dataset.tag; st.tags = st.tags.includes(t) ? st.tags.filter((x) => x !== t) : [...st.tags, t]; load(); return; }
    if (e.target.closest('[data-role="more"]')) { st.page += 1; load(false); return; }
    if (e.target.closest('[data-role="back"]')) { st.similarOf = null; load(); return; }
    if (e.target.closest('[data-role="fromimg"]')) { fileIn.click(); return; }
    if (e.target.closest('[data-role="expand"]')) { openPoseModal(onPick, getSelected, inst); return; }
    const sb = e.target.closest("[data-star]");
    if (sb) {
      const x = st.items.find((i) => i.id === sb.dataset.star);
      if (!x) return;
      x.star = !x.star;
      await api("/api/posepacks/star", { json: { id: x.id, on: x.star } });
      for (const b of activePoseBrowsers) {
        const it = b.st.items.find((i) => i.id === x.id);
        if (it) { it.star = x.star; b.draw(); }
      }
      return;
    }
    const sm = e.target.closest("[data-sim]");
    if (sm) { st.similarOf = st.items.find((i) => i.id === sm.dataset.sim); load(); return; }
    const p = e.target.closest(".pack-pose");
    if (p && opts.batch && (opts.batch.mode() || e.metaKey || e.shiftKey)) {
      opts.batch.toggle(st.items.find((i) => i.id === p.dataset.id)); draw(); return;
    }
    if (p) {
      const x = st.items.find((i) => i.id === p.dataset.id);
      const off = getSelected() === x.id;
      onPick(off ? null : x); draw();
      if (!off) api("/api/posepacks/used", { json: { id: x.id } }).catch(() => {});
    }
  });

  root.addEventListener("change", (e) => {
    if (e.target.matches('[data-role="source"]')) {
      const v = e.target.value;
      if (v.startsWith("pack:")) st.pack = v.slice(5); else { st.cat = v.slice(4); st.pack = ""; }
      load();
    }
    if (e.target.matches("[data-group]")) {
      const f = st.filters.find((x) => x.name === e.target.dataset.group), opts_ = f ? f.options.map(([o]) => o) : [];
      st.tags = st.tags.filter((t) => !opts_.includes(t)).concat(e.target.value ? [e.target.value] : []);
      load();
    }
  });

  let t;
  root.addEventListener("input", (e) => {
    if (e.target.matches('[data-role="q"]')) {
      clearTimeout(t);
      t = setTimeout(() => {
        st.q = e.target.value.trim();
        load().then(() => {
          const i = root.querySelector('[data-role="q"]');
          i?.focus();
          i?.setSelectionRange(i.value.length, i.value.length);
        });
      }, 250);
    }
  });

  return inst;
}

export let modalBrowser = null;
let modalPick = null;
let modalSel = null;
let modalSource = null;

export function openPoseModal(onPick, getSelected, sourceBrowser = null) {
  modalPick = onPick; modalSel = getSelected; modalSource = sourceBrowser;
  if (!modalBrowser) {
    modalBrowser = packBrowser($("#mPacks"), (x) => {
      modalPick?.(x);
      if (modalSource) {
        syncBrowserFilters(modalBrowser, modalSource);
        modalSource.load();
      }
      if (x) closePoseModal();
    }, () => modalSel?.(), {
      big: true,
      get batch() { return $("#view-generate").classList.contains("is-active") ? poseBatchApi : null; },
    });
  }
  $("#poseModalFor").textContent = $("#view-generate").classList.contains("is-active") ? "· for Generate" : "· for Krita";
  if (modalSource) {
    syncBrowserFilters(modalSource, modalBrowser);
  }
  $("#poseModal").hidden = false;
  modalBrowser.load();
}

export function closePoseModal() {
  $("#poseModal").hidden = true;
  if (modalSource) {
    syncBrowserFilters(modalBrowser, modalSource);
    modalSource.load();
  }
}

$("#poseModalClose")?.addEventListener("click", closePoseModal);
$("#poseModal")?.addEventListener("click", (e) => { if (e.target.id === "poseModal") closePoseModal(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#poseModal")?.hidden) {
    e.stopPropagation();
    closePoseModal();
  }
});

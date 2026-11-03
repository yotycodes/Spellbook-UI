// standalone/web/src/views/library.js
// Prompt library view: filters, search, responsive grid, pagination, collections, multi-select, character cards.

import { $, $$, api, esc, fmt, label, toast, promptDialog } from "../api.js";
import { state, savePrefs, pushState, gen, multi, charState } from "../state.js";
import { select, getRecord } from "../components/inspector.js";
import { showView } from "../main.js";
import { genParams, openInGenerate, startPolling, fillCollections } from "./generate.js";

export function fillSelect(el, values, value) {
  el.innerHTML = values.map((v) => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(label(v))}</option>`).join("");
}

export function renderFilters() {
  const m = state.meta;
  if (!m) return;
  fillSelect($("#f-base"), m.bases, state.base);
  fillSelect($("#f-theme"), m.themes, state.theme);
  fillSelect($("#f-rating"), m.ratings, state.rating);
  fillSelect($("#f-sort"), m.sorts, state.sort);
  fillSelect($("#f-collection"), ["All", ...m.collections], state.collection);
  $("#f-runnable")?.setAttribute("aria-pressed", String(state.runnable));
  $$("#perPage button").forEach((b) => b.classList.toggle("is-on", Number(b.dataset.v) === state.perPage));
  renderActiveChips();
}

export function renderActiveChips() {
  const chips = [];
  if (state.q) chips.push(["q", `“${state.q}”`]);
  if (state.base !== "All") chips.push(["base", state.base]);
  if (state.theme !== "All") chips.push(["theme", state.theme]);
  if (state.collection !== "All") chips.push(["collection", state.collection]);
  if (state.runnable) chips.push(["runnable", "Runnable only"]);
  if (state.similar) chips.push(["similar", "Similar to your image"]);
  $("#activeChips").innerHTML = chips.map(([k, l]) =>
    `<span class="achip">${esc(l)}<button data-clear="${k}" title="Remove filter"><i class="ph ph-x"></i></button></span>`).join("");
}

$("#activeChips")?.addEventListener("click", (e) => {
  const k = e.target.closest("[data-clear]")?.dataset.clear;
  if (!k) return;
  if (k === "q") { state.q = ""; $("#q").value = ""; }
  else if (k === "runnable") state.runnable = false;
  else if (k === "similar") state.similar = false;
  else state[k] = "All";
  newSearch();
});

const bindSelect = (id, key) => $(id)?.addEventListener("change", (e) => { state[key] = e.target.value; savePrefs(); newSearch(); });
bindSelect("#f-base", "base"); bindSelect("#f-theme", "theme"); bindSelect("#f-rating", "rating");
bindSelect("#f-sort", "sort"); bindSelect("#f-collection", "collection");
$("#f-runnable")?.addEventListener("click", () => { state.runnable = !state.runnable; newSearch(); });

// -- Library import actions ----------------
async function importDone(r) {
  const extra = r.note ? ` — ${r.note}` : "";
  toast(`Imported ${r.imported} prompt${r.imported === 1 ? "" : "s"}${extra}`, r.imported ? "ok" : "info");
  state.libError = null;
  await newSearch();
  if (r.imported) showView("library");  // renew filters/cards against the new content
}

$("#gridEmpty")?.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.id === "impShelf") {
    b.disabled = true;
    try { await importDone(await api("/api/library/starter-shelf", { method: "POST" })); }
    catch (err) { toast(err.message, "err"); b.disabled = false; }
    return;
  }
  if (b.id === "impPng") {
    if (!state._libPath) {
      try { state._libPath = (await api("/api/settings")).folders.find((f) => f.id === "library_path")?.path || ""; }
      catch (_) { /* default stays empty */ }
    }
    const folder = await promptDialog("Import images from which folder? (PNGs with saved generation info)", state._libPath || "");
    if (!folder) return;
    b.disabled = true;
    try { await importDone(await api("/api/library/import/pngs", { json: { folder } })); }
    catch (err) { toast(err.message, "err"); b.disabled = false; }
    return;
  }
  if (b.id === "impFile") {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".json,.csv"; inp.hidden = true;
    inp.addEventListener("change", async () => {
      if (!inp.files?.[0]) return;
      const fd = new FormData(); fd.append("file", inp.files[0]);
      const isCsv = inp.files[0].name.toLowerCase().endsWith(".csv");
      try { await importDone(await api(isCsv ? "/api/library/import/csv" : "/api/library/import/json", { method: "POST", body: fd })); }
      catch (err) { toast(err.message, "err"); }
    });
    inp.click();
    return;
  }
});

let qTimer;
$("#q")?.addEventListener("input", (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); newSearch(); }, 280); });
$("#q")?.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(qTimer); state.q = e.target.value.trim(); newSearch(); } if (e.key === "Escape") e.target.blur(); });
$$("#perPage button").forEach((b) => b.addEventListener("click", () => { state.perPage = Number(b.dataset.v); savePrefs(); newSearch(); }));

export function setCardSize(v) {
  state.cardSize = v; savePrefs();
  $("#grid")?.classList.remove("size-s", "size-m", "size-l"); $("#grid")?.classList.add(`size-${v}`);
  $$("#cardSize button").forEach((b) => b.classList.toggle("is-on", b.dataset.v === v));
}
$$("#cardSize button").forEach((b) => b.addEventListener("click", () => setCardSize(b.dataset.v)));

$("#clearFilters")?.addEventListener("click", () => {
  Object.assign(state, { q: "", base: "All", theme: "All", collection: "All", runnable: false }); $("#q").value = ""; newSearch();
});

export let searchToken = 0;

export async function newSearch() {
  state.similar = false;
  state.page = 0;
  state.seed = Math.floor(Math.random() * 1e9);
  renderFilters();
  await runSearch();
}

export async function runSearch(keepSelection = false) {
  if (state.similar) { state.similar = false; renderActiveChips(); }
  const token = ++searchToken;
  renderSkeleton();
  const p = new URLSearchParams({
    q: state.q, base: state.base, theme: state.theme, rating: state.rating, sort: state.sort,
    per_page: state.perPage, page: state.page, collection: state.collection, runnable: state.runnable, seed: state.seed,
  });
  try {
    const res = await api(`/api/search?${p}`);
    if (token !== searchToken) return;
    Object.assign(state, { items: res.items, total: res.total, page: res.page, pages: res.pages });
    state.libError = res.library_error || null;
    if (!keepSelection) state.sel = -1;
    pushState(true);
    renderGrid();
    renderPager();
    renderCharCard();
    renderMulti();
    $("#gridWrap").scrollTop = 0;
  } catch (e) {
    toast(`Search didn't load (${esc(e.message)}). Check that Spellbook UI is still running, then change a filter to retry.`, "err");
  }
}

// Empty states. "No library yet" shows the import CTAs (first run on a fresh machine);
// a no-match result keeps the plain filter-clear hint.
function renderEmptyState() {
  const empty = $("#gridEmpty");
  if (state.libError) {
    empty.innerHTML = `
      <i class="ph ph-book-open-text" aria-hidden="true"></i>
      <h3>Your library is empty</h3>
      <p>Bring prompts in — a folder of images with saved generation info, a sidecar file, or the built-in starter shelf.</p>
      <div class="empty-actions">
        <button class="btn btn-primary" id="impShelf"><i class="ph ph-wand-magic-sparkles"></i>Add the starter shelf <span class="dim">(50 prompts)</span></button>
        <button class="btn" id="impPng"><i class="ph ph-folder-open"></i>Import images folder…</button>
        <button class="btn" id="impFile"><i class="ph ph-file-plus"></i>Import file (JSON / CSV)…</button>
        <a class="btn btn-ghost" href="/api/library/export.json" download title="Nothing to export yet" aria-disabled="true" onclick="return false"><i class="ph ph-download-simple"></i>Export</a>
      </div>
      <p class="dim">Point Settings → Prompt library at an existing folder, or see <b>Library import</b> in the docs for the file format.</p>`;
    empty.hidden = false;
    return;
  }
  empty.innerHTML = `
    <i class="ph ph-image-broken" aria-hidden="true"></i>
    <h3>No prompts match</h3>
    <p>Try a different theme, clear the search, or turn off Runnable.</p>
    <button class="btn" id="clearFilters">Clear filters</button>`;
  empty.hidden = false;
}

export function renderSkeleton() {
  const n = Math.min(state.perPage, 36);
  $("#grid").innerHTML = Array.from({ length: n }, () => `<div class="card"></div>`).join("");
  renderGrid.html = null;
  $("#gridEmpty").hidden = true;
}

export function renderGrid() {
  const grid = $("#grid");
  if (!grid) return;
  const empty = $("#gridEmpty");
  empty.hidden = state.items.length > 0;
  if (state.items.length === 0) renderEmptyState();
  if (!renderGrid.played) { renderGrid.played = true; grid.classList.add("enter"); } else grid.classList.remove("enter");
  const html = state.items.map((it, i) => `
    <button class="card${i === state.sel ? " is-selected" : ""}" data-i="${i}" title="#${it.id}" style="--i:${Math.min(i, 30)}">
      <img loading="lazy" decoding="async" src="/api/thumb/${it.id}" alt="">
      ${it.fav ? `<span class="card-fav"><i class="ph-fill ph-bookmark-simple"></i></span>` : ""}
      <span class="card-meta"><span>${esc(it.base)}</span><span><i class="ph-fill ph-heart"></i>${fmt(it.react)}</span></span>
    </button>`).join("");
  if (html === renderGrid.html) return;
  renderGrid.html = html;
  grid.innerHTML = html;
  $$(".card img", grid).forEach((img) => {
    const card = img.parentElement;
    const done = () => card.classList.add("loaded");
    if (img.complete && img.naturalWidth) done();
    img.addEventListener("load", done);
    img.addEventListener("error", () => { card.classList.add("loaded", "broken"); img.remove(); });
  });
}

$("#grid")?.addEventListener("click", (e) => {
  const card = e.target.closest(".card[data-i]");
  if (card && !(e.metaKey || e.shiftKey)) select(Number(card.dataset.i));
});

export function renderPager() {
  const first = state.total ? state.page * state.perPage + 1 : 0;
  const last = state.page * state.perPage + state.items.length;
  $("#pagerCount").innerHTML = state.total
    ? `<b>${fmt(state.total)}</b> prompts &nbsp;·&nbsp; ${fmt(first)} to ${fmt(last)}`
    : "No results";
  $("#pgInput").value = state.page + 1;
  $("#pgInput").max = state.pages;
  $("#pgTotal").textContent = fmt(state.pages);
  $("#pgFirst").disabled = $("#pgPrev").disabled = state.page <= 0;
  $("#pgNext").disabled = $("#pgLast").disabled = state.page >= state.pages - 1;
}

export const goPage = (p) => {
  const np = Math.max(0, Math.min(state.pages - 1, p));
  if (np !== state.page) { state.page = np; pushState(); runSearch(); }
};
$("#pgFirst")?.addEventListener("click", () => goPage(0));
$("#pgPrev")?.addEventListener("click", () => goPage(state.page - 1));
$("#pgNext")?.addEventListener("click", () => goPage(state.page + 1));
$("#pgLast")?.addEventListener("click", () => goPage(state.pages - 1));
$("#pgInput")?.addEventListener("change", (e) => goPage(Number(e.target.value || 1) - 1));

export async function renderCollections() {
  const list = await api("/api/collections");
  const cards = list.map((c) => `
    <div class="coll" data-name="${esc(c.name)}" role="button" tabindex="0">
      <div class="coll-cover" ${c.cover ? `style="background-image:url('/api/thumb/${c.cover}')"` : ""}>${c.cover ? "" : `<i class="ph ph-bookmarks-simple"></i>`}</div>
      <div class="coll-body"><b>${esc(label(c.name))}</b><span>${c.count} saved</span></div>
      ${c.name !== state.meta?.collections[0] ? `<button class="icon-btn" data-del="${esc(c.name)}" title="Delete collection" aria-label="Delete collection"><i class="ph ph-trash"></i></button>` : ""}
    </div>`).join("");
  $("#collections").innerHTML = cards
    || `<div class="empty"><i class="ph ph-bookmarks-simple"></i><h3>No collections yet</h3><p>Open a prompt and press S to save it.</p></div>`;
  if (cards && !list.some((c) => c.count)) $("#collections").insertAdjacentHTML("beforeend",
    `<div class="empty"><i class="ph ph-star" aria-hidden="true"></i><h3>Nothing saved yet</h3><p>Open the Library, pick a prompt and press S — favorites and collections fill up from there.</p></div>`);
}

$("#collections")?.addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]")?.dataset.del;
  if (del) {
    e.stopPropagation();
    const r = await api("/api/collections/delete", { json: { name: del } });
    state.meta.collections = r.collections;
    if (state.collection === del) state.collection = "All";
    renderFilters(); renderCollections();
    toast(`Deleted “${esc(del)}”. The prompts stay in the library.`, "info",
      { label: "Undo", fn: async () => {
          await api("/api/collections/restore", { json: { name: del, ids: r.ids || [] } });
          renderCollections();
        } });
    return;
  }
  const name = e.target.closest(".coll")?.dataset.name;
  if (!name) return;
  Object.assign(state, { collection: name, q: "", base: "All", theme: "All", rating: "All (incl. mature)", runnable: false });
  $("#q").value = "";
  showView("library");
  newSearch();
});

export function renderMulti() {
  $$(".card").forEach((c) => c.classList.toggle("multi", multi.has(state.items[Number(c.dataset.i)]?.id)));
  $("#multiBar").hidden = !multi.size;
  $("#multiCount").textContent = `${multi.size} selected`;
}

$("#grid")?.addEventListener("click", (e) => {
  const card = e.target.closest(".card[data-i]"); if (!card || !(e.metaKey || e.shiftKey)) return;
  e.stopImmediatePropagation();
  const i = Number(card.dataset.i);
  if (e.shiftKey && gen.lastMulti != null) {
    const [a, b] = [Math.min(gen.lastMulti, i), Math.max(gen.lastMulti, i)];
    for (let k = a; k <= b; k++) multi.add(state.items[k].id);
  } else { const id = state.items[i].id; multi.has(id) ? multi.delete(id) : multi.add(id); }
  gen.lastMulti = i; renderMulti();
}, true);

$("#multiClear")?.addEventListener("click", () => { multi.clear(); renderMulti(); });
$("#multiSave")?.addEventListener("click", async () => {
  const name = await promptDialog("Save the selected prompts to which collection?", state.meta?.collections[0]);
  if (!name) return;
  let r; for (const id of multi) r = await api("/api/favorites", { json: { id, collection: name.trim() } });
  if (r) {
    try { state.meta = await api("/api/meta"); } catch {}
    fillSelect($("#f-collection"), ["All", ...state.meta.collections], state.collection);
    fillCollections();
    // Refresh grid fav badges
    await runSearch(true);
  }
  toast(`Saved ${multi.size} to ${esc(name)}`); multi.clear(); renderMulti();
});

$("#multiQueue")?.addEventListener("click", async () => {
  if (!gen.opts?.online) { showView("generate"); return toast("Start Forge first, then queue again", "info"); }
  const base = genParams(); const jobs = [];
  for (const id of multi) {
    const r = await api(`/api/record/${id}/gen`).catch(() => null); if (!r) continue;
    jobs.push({
      params: {
        ...base, mode: "txt2img", prompt: r.prompt, negative: base.style ? base.negative : r.negative, seed: -1, count: 1,
        ...(base.style ? {} : { sampler: r.sampler, scheduler: r.scheduler, steps: r.steps, cfg: r.cfg, width: r.width, height: r.height }),
      },
      label: `#${id} · ${r.prompt.slice(0, 50)}`,
    });
  }
  await api("/api/gen/run", { json: { jobs } });
  toast(`Queued ${jobs.length} prompts${base.style ? ` in ${esc(base.style)}` : ""}`); multi.clear(); renderMulti(); startPolling();
});

export async function renderCharCard() {
  const q = (state.q || "").trim().toLowerCase();
  const hit = (state.meta?.heroes || []).find(([h]) => h.toLowerCase() === q);
  if (!hit || state.similar) { $("#charCard").hidden = true; charState.name = null; return; }
  if (charState.name !== hit[0] || charState.rating !== state.rating) {
    charState.data = await api(`/api/character/${encodeURIComponent(hit[0])}?rating=${encodeURIComponent(state.rating === "SFW" ? "SFW" : "All")}`).catch(() => null);
    charState.name = hit[0]; charState.rating = state.rating;
    charState.style = charState.data?.styles.find((x) => x.installed)?.name || null;
  }
  const d = charState.data;
  if (!d) { $("#charCard").hidden = true; return; }
  const n = Math.min(12, d.ids.length);
  $("#charCard").innerHTML = `
    <img src="/api/thumb/${d.ids[0]}" alt="">
    <div>
      <h2>${esc(d.hero)}</h2>
      <div class="char-meta">${esc(d.universe || "Character")}${d.gender ? ` · ${esc(d.gender)}` : ""} · ${fmt(d.total)} prompts (${fmt(d.sfw)} SFW)</div>
      <div class="char-rows">
        <div class="char-row"><b>LoRAs</b>${d.loras.length ? d.loras.map((l) => `<span class="chip static" title="Installed"><i class="ph ph-puzzle-piece"></i>${esc(l)}</span>`).join("") : `<span class="muted">none installed for this character</span>`}</div>
        <div class="char-row"><b>Styles</b>${d.styles.map((st) => `<button class="chip style-pick-chip${st.name === charState.style ? " is-on" : ""}" data-style="${esc(st.name)}" title="Fits ${st.count} of their prompts${st.installed ? "" : " (not one of your styles yet)"}">${esc(st.name)}</button>`).join("")}</div>
      </div>
    </div>
    <div class="char-actions">
      <div class="seed-row"><select id="charCount" class="input" aria-label="How many prompts">${[4, 8, 12, 24].filter((x, i) => x <= d.ids.length || i === 0).map((x) => `<option value="${x}" ${x === n ? "selected" : ""}>Top ${Math.min(x, d.ids.length)} prompts</option>`).join("")}</select></div>
      <button class="btn btn-primary" id="charQueue"><i class="ph ph-stack"></i>Queue in Generate</button>
      <button class="btn" id="charOpen"><i class="ph ph-magic-wand"></i>Open best in Generate</button>
    </div>`;
  $("#charCard").hidden = false;
}

$("#charCard")?.addEventListener("click", async (e) => {
  const chip = e.target.closest("[data-style]");
  if (chip) { charState.style = charState.style === chip.dataset.style ? null : chip.dataset.style; renderCharCard(); return; }
  const d = charState.data; if (!d) return;
  if (e.target.closest("#charOpen")) {
    const k = charState.style ? (await getRecord(d.ids[0]).catch(() => null))?.krita : null;
    openInGenerate(d.ids[0], charState.style ? { style: charState.style, styleFill: true, prompt: k?.prompt, negative: "" } : undefined);
    return;
  }
  if (e.target.closest("#charQueue")) {
    const n = Number($("#charCount").value);
    if (!gen.opts?.online) { showView("generate"); return toast("Start Forge first, then queue again", "info"); }
    const st = (gen.opts.styles || []).find((x) => x.name === charState.style);
    const base = genParams();
    const jobs = [];
    for (const id of d.ids.slice(0, n)) {
      const r = await api(`/api/record/${id}/gen`).catch(() => null);
      if (!r) continue;
      const k = st ? (await getRecord(id).catch(() => null))?.krita?.prompt : null;
      jobs.push({
        params: {
          ...base, mode: "txt2img", source: undefined, prompt: k || r.prompt, negative: st ? "" : r.negative, seed: -1, count: 1,
          style: st ? st.name : "", ...(st ? { model: st.model || base.model, sampler: st.sampler, scheduler: st.scheduler, steps: st.steps, cfg: st.cfg, clip_skip: st.clip_skip }
            : { sampler: r.sampler, scheduler: r.scheduler, steps: r.steps, cfg: r.cfg, width: r.width, height: r.height }),
        },
        label: `${d.hero} · #${id}`,
      });
    }
    await api("/api/gen/run", { json: { jobs } });
    toast(`Queued ${jobs.length} ${esc(d.hero)} prompts${st ? ` in ${esc(st.name)}` : ""}`);
    startPolling();
  }
});

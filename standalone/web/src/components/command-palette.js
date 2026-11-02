// standalone/web/src/components/command-palette.js
// Command palette (⌘K) and shortcuts help overlay.

import { $, esc } from "../api.js";
import { state, savePrefs, forge } from "../state.js";
import { showView, toggleForge } from "../main.js";
import { cleanPromptElement } from "../views/interrogate.js";
import { sendToKrita } from "./inspector.js";
import { openInGenerate } from "../views/generate.js";
import { newSearch } from "../views/library.js";

export const pal = { items: [], sel: 0 };

export const titleCase = (t) => t.replace(/\b\w/g, (c) => c.toUpperCase());

export function paletteCommands() {
  const views = [
    ["generate", "Generate", "ph-magic-wand", "1"],
    ["library", "Library", "ph-squares-four", "2"],
    ["collections", "Collections", "ph-bookmarks-simple", "3"],
    ["interrogate", "Interrogate", "ph-scan", "4"],
    ["settings", "Settings", "ph-gear-six", "5"],
  ];
  const lib = (fn) => () => { showView("library"); fn(); newSearch(); };
  const cmds = [
    ...views.map(([v, l, i, k]) => ({ group: "Go to", label: l, icon: i, hint: k, run: () => showView(v) })),
    { group: "Go to", label: "Tag Cleaner", icon: "ph-broom", run: () => showView("cleaner") },
    { group: "Actions", label: "Clean prompt in Generate", icon: "ph-broom", run: () => cleanPromptElement($("#gPrompt")) },
    { group: "Actions", label: forge.state === "on" ? "Stop Forge" : "Start Forge", icon: "ph-power", run: toggleForge },
    { group: "Actions", label: state.runnable ? "Show all prompts (turn off Runnable)" : "Only runnable prompts", icon: "ph-check-circle", run: lib(() => { state.runnable = !state.runnable; }) },
    { group: "Actions", label: "Clear all filters", icon: "ph-x-circle", run: () => $("#clearFilters")?.click() },
    { group: "Actions", label: "Shuffle the library", icon: "ph-shuffle", run: lib(() => { state.sort = "Shuffle"; savePrefs(); }) },
    ...(state.meta?.ratings || []).map((r) => ({ group: "Rating", label: `Rating: ${r}`, icon: "ph-eye", run: lib(() => { state.rating = r; savePrefs(); }) })),
  ];
  if (state.record) {
    cmds.push(
      { group: "This prompt", label: "Open in Generate", icon: "ph-magic-wand", hint: "G", run: () => openInGenerate(state.record.id) },
      { group: "This prompt", label: "Send to Krita", icon: "ph-paper-plane-tilt", hint: "K", run: sendToKrita },
      { group: "This prompt", label: "Save to collection", icon: "ph-bookmark-simple", hint: "S", run: () => $("#iSave")?.click() },
    );
  }
  cmds.push(...(state.meta?.themes || []).filter((t) => t !== "All").map((t) => ({ group: "Theme", label: t, icon: "ph-tag", run: lib(() => { state.theme = t; }) })));
  cmds.push(...(state.meta?.heroes || []).map(([h, n]) => ({
    group: "Character", label: titleCase(h), icon: "ph-user", hint: `${n}`,
    run: lib(() => { state.q = h; $("#q").value = h; }),
  })));
  return cmds;
}

export function renderPalette() {
  const q = $("#palQ").value.trim().toLowerCase();
  const all = paletteCommands();
  const words = q.split(/\s+/).filter(Boolean);
  let items = words.length
    ? all.filter((c) => words.every((w) => `${c.group} ${c.label}`.toLowerCase().includes(w)))
    : all.filter((c) => c.group !== "Character" && c.group !== "Theme");
  items = items.slice(0, 60);
  pal.items = items; pal.sel = Math.min(pal.sel, Math.max(0, items.length - 1));
  let last = "";
  $("#palList").innerHTML = items.map((c, i) => {
    const head = c.group !== last ? `<li class="pal-group" aria-hidden="true">${esc(c.group)}</li>` : "";
    last = c.group;
    return `${head}<li role="option" data-i="${i}" class="${i === pal.sel ? "is-on" : ""}"><i class="ph ${c.icon}"></i>${esc(c.label)}${c.hint ? `<small>${esc(c.hint)}</small>` : ""}</li>`;
  }).join("") || `<li class="pal-group">Nothing matches</li>`;
  $("#palList li.is-on")?.scrollIntoView({ block: "nearest" });
}

export function togglePalette(open = $("#palette")?.hidden) {
  if (!$("#palette")) return;
  $("#palette").hidden = !open;
  if (open) { $("#palQ").value = ""; pal.sel = 0; renderPalette(); $("#palQ")?.focus(); }
}

export function runPalette(i) {
  const c = pal.items[i];
  if (!c) return;
  togglePalette(false);
  c.run();
}

$("#palQ")?.addEventListener("input", () => { pal.sel = 0; renderPalette(); });
$("#palQ")?.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    pal.sel = (pal.sel + (e.key === "ArrowDown" ? 1 : -1) + pal.items.length) % Math.max(1, pal.items.length);
    renderPalette();
  } else if (e.key === "Enter") {
    e.preventDefault();
    runPalette(pal.sel);
  } else if (e.key === "Escape") {
    e.preventDefault();
    togglePalette(false);
  }
});
$("#palList")?.addEventListener("click", (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) runPalette(Number(li.dataset.i));
});
$("#palette")?.addEventListener("click", (e) => { if (e.target.id === "palette") togglePalette(false); });
$("#helpBtn")?.addEventListener("click", () => { $("#help").hidden = false; });
$("#help")?.addEventListener("click", (e) => { if (e.target.id === "help") $("#help").hidden = true; });

// standalone/web/src/state.js
// Central state & localStorage syncing.

export const state = {
  meta: null,
  q: "", base: "All", theme: "All", rating: "SFW", sort: "Most reactions", collection: "All", runnable: false,
  perPage: 120, page: 0, seed: 1, pages: 1, total: 0, items: [],
  sel: -1, record: null, poseGroup: "Pin-up", poseKey: null, cardSize: "m", view: "library", tab: "krita",
  density: "comfortable", darkMode: "auto",
};

try {
  const saved = JSON.parse(localStorage.getItem("pl-prefs") || "{}");
  Object.assign(state, saved);
} catch {}

if (!["SFW", "All", "NSFW"].includes(state.poseRating)) state.poseRating = "SFW";

export const pushState = () => {};

export const savePrefs = () => {
  try {
    localStorage.setItem("pl-prefs", JSON.stringify({
      rating: state.rating, sort: state.sort, perPage: state.perPage, poseGroup: state.poseGroup,
      cardSize: state.cardSize, view: state.view, tab: state.tab, poseRating: state.poseRating,
      poseClearOnly: !!state.poseClearOnly, poseDepthOnly: !!state.poseDepthOnly,
      density: state.density, darkMode: state.darkMode,
    }));
  } catch {}
};

export const forge = {
  state: "off",
  timer: null,
};

export const ir = {
  res: null,
  on: new Set(),
  thresh: 0.35,
  modes: new Set(["reference"]),
  similar: [],
};

export const charState = {
  name: null,
  style: null,
  data: null,
  rating: null,
};

export const multi = new Set();
export const activePoseBrowsers = new Set();

export const themeUi = {
  list: [],
  def: "graphite",
  saved: "graphite",
  preview: null,
};

export const PREFS_GEN = "pl-gen";
export const NATIVE = 1024;

export const gen = {
  opts: null,
  gallery: [],
  lb: -1,
  polling: false,
  lastJob: null,
  activeSubTab: "tune",
  posePack: null,
  poseTagText: "",
  poseAdded: [],
  poseBatch: [],
  batchMode: false,
  galStar: "all",
  picked: new Set(),
  seen: null,
  fresh: new Set(),
  entered: new Set(),
  qStatus: new Map(),
  qSeen: new Set(),
  unseen: 0,
  pillHidden: false,
  lastNew: null,
  doneCount: null,
  lastProgress: null,
  wasBusy: false,
  finished: false,
  seenErr: new Set(),
  moreLike: [],
  lastMulti: null,
  settings: null,
  pending: null,
  clipSkip: 0,
  distilled: null,
  depthSet: false,
  variation: false,
};

try { gen.poseAdded = JSON.parse(localStorage.getItem("pl-pose-added") || "[]"); } catch { gen.poseAdded = []; }
try { gen.poseBatch = JSON.parse(localStorage.getItem("pl-pose-batch") || "[]"); } catch { gen.poseBatch = []; }

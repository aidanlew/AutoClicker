"use strict";

const $ = (id) => document.getElementById(id);

const MIN_CPS = 0.01;
const MAX_CPS = 1000;
const SLIDER_MAX = 1000; // slider is log-scaled over 1..1000 clicks/second
const DEFAULT_HINT = "Works while any app is focused. Function keys avoid clashes.";

const MAC_MODS = { "<ctrl>": "⌃", "<alt>": "⌥", "<shift>": "⇧", "<cmd>": "⌘" };
const NAMED_KEYS = {
  Space: "<space>", Enter: "<enter>", Tab: "<tab>", Backspace: "<backspace>",
  Delete: "<delete>", Insert: "<insert>", Home: "<home>", End: "<end>",
  PageUp: "<page_up>", PageDown: "<page_down>", ArrowUp: "<up>", ArrowDown: "<down>",
  ArrowLeft: "<left>", ArrowRight: "<right>", Pause: "<pause>", ScrollLock: "<scroll_lock>",
};
const KEY_LABELS = { up: "↑", down: "↓", left: "←", right: "→" };

let api = null;
let platform = "";
let warning = null;
let settings = {};
let saveTimer = null;
let capturingHotkey = false;
let cursorOverApp = false;

// ---------- persistence ----------

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api.save_settings(payload()), 250);
}

function payload() {
  const { hotkey, always_on_top, ...rest } = settings;
  return rest;
}

// ---------- click speed ----------

const fmt = (n) => String(Math.round(n * 100) / 100);
const cpsToSlider = (cps) => Math.round((Math.log10(Math.max(1, cps)) / 3) * SLIDER_MAX);
const sliderToCps = (v) => Math.round(Math.pow(10, (v / SLIDER_MAX) * 3));

function setCps(cps, source) {
  settings.cps = Math.min(MAX_CPS, Math.max(MIN_CPS, cps));
  if (source !== "cps") $("cps").value = fmt(settings.cps);
  if (source !== "interval") $("interval").value = fmt(1000 / settings.cps);
  if (source !== "slider") $("speed").value = cpsToSlider(settings.cps);
  save();
}

function bindSpeed() {
  $("cps").addEventListener("input", (e) => {
    const cps = parseFloat(e.target.value);
    if (cps > 0) setCps(cps, "cps");
  });
  $("interval").addEventListener("input", (e) => {
    const ms = parseFloat(e.target.value);
    if (ms > 0) setCps(1000 / ms, "interval");
  });
  // Tidy whatever was typed once the field loses focus.
  for (const id of ["cps", "interval"]) {
    $(id).addEventListener("blur", () => setCps(settings.cps));
  }
  $("speed").addEventListener("input", (e) => setCps(sliderToCps(+e.target.value), "slider"));
  $("presets").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) setCps(+b.dataset.cps);
  });
}

// ---------- click options ----------

function renderSeg(el, value) {
  for (const b of el.children) {
    b.classList.toggle("active", b.dataset.value === value);
    b.setAttribute("aria-checked", b.dataset.value === value);
  }
}

function bindSeg(el, key) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    settings[key] = b.dataset.value;
    renderSeg(el, settings[key]);
    renderHoldMode();
    save();
  });
}

function renderHoldMode() {
  // Speed and click limits don't apply while holding the button down.
  const hold = settings.click_type === "hold";
  $("speedSection").classList.toggle("dim", hold);
  $("stopAfterRow").classList.toggle("dim", hold);
}

function renderPosition() {
  const p = settings.position;
  $("posText").textContent = p ? `Pinned at ${p[0]}, ${p[1]}` : "Follows cursor";
}

function bindPosition() {
  $("pin").addEventListener("click", async () => {
    $("pin").disabled = true;
    $("posText").textContent = "Click the spot to pin…";
    const pos = await api.pick_position();
    $("pin").disabled = false;
    if (pos) {
      settings.position = pos;
      save();
    }
    renderPosition();
  });
  $("follow").addEventListener("click", () => {
    settings.position = null;
    renderPosition();
    save();
  });
}

// ---------- limits ----------

function renderLimits() {
  $("stopAfter").value = settings.stop_after || "";
  $("delay").value = fmt(settings.start_delay);
}

function bindLimits() {
  $("stopAfter").addEventListener("input", (e) => {
    const n = parseInt(e.target.value, 10);
    settings.stop_after = n > 0 ? n : null;
    save();
  });
  $("delay").addEventListener("input", (e) => {
    const s = parseFloat(e.target.value);
    settings.start_delay = s > 0 ? s : 0;
    save();
  });
  for (const id of ["stopAfter", "delay"]) {
    $(id).addEventListener("blur", renderLimits);
  }
}

// ---------- hotkey ----------

function hotkeyLabel(combo) {
  const mac = platform === "darwin";
  const pcMods = { "<ctrl>": "Ctrl", "<alt>": "Alt", "<shift>": "Shift", "<cmd>": platform === "win32" ? "Win" : "Super" };
  const parts = combo.split("+").map((part) => {
    const mod = (mac ? MAC_MODS : pcMods)[part];
    if (mod) return mod;
    const name = part.replace(/^<|>$/g, "");
    if (name.length === 1) return name.toUpperCase();
    if (KEY_LABELS[name]) return KEY_LABELS[name];
    if (/^f\d+$/.test(name)) return name.toUpperCase();
    return name.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  });
  return parts.join(mac ? "" : " + ");
}

// Converts a keydown event to pynput's GlobalHotKeys format, e.g. "<shift>+c".
// Returns undefined for a lone modifier (keep waiting) and null if unsupported.
function toCombo(e) {
  if (["Shift", "Control", "Alt", "Meta"].includes(e.key)) return undefined;
  let key;
  let m;
  if ((m = /^Key([A-Z])$/.exec(e.code))) key = m[1].toLowerCase();
  else if ((m = /^Digit(\d)$/.exec(e.code))) key = m[1];
  else if ((m = /^F(\d{1,2})$/.exec(e.code))) key = `<f${m[1]}>`;
  else key = NAMED_KEYS[e.code];
  if (!key) return null;
  // Shift+digit and (on macOS) Option+character produce a different character,
  // which the global listener would never match.
  if (key.length === 1 && ((e.shiftKey && /\d/.test(key)) || (e.altKey && platform === "darwin"))) return null;
  const mods = [];
  if (e.ctrlKey) mods.push("<ctrl>");
  if (e.altKey) mods.push("<alt>");
  if (e.shiftKey) mods.push("<shift>");
  if (e.metaKey) mods.push("<cmd>");
  return [...mods, key].join("+");
}

function renderHotkey() {
  $("hotkey").textContent = hotkeyLabel(settings.hotkey);
}

function endHotkeyCapture() {
  capturingHotkey = false;
  api.pause_hotkey(false);
  $("changeHotkey").textContent = "Change…";
  $("hotkeyHint").textContent = DEFAULT_HINT;
  renderHotkey();
}

function bindHotkey() {
  $("changeHotkey").addEventListener("click", () => {
    if (capturingHotkey) return endHotkeyCapture();
    capturingHotkey = true;
    api.pause_hotkey(true);
    $("changeHotkey").textContent = "Press keys…";
    $("hotkeyHint").textContent = "Press the new shortcut, or Esc to cancel.";
  });
  document.addEventListener("keydown", async (e) => {
    if (!capturingHotkey) return;
    e.preventDefault();
    if (e.key === "Escape") return endHotkeyCapture();
    const combo = toCombo(e);
    if (combo === undefined) return;
    if (combo === null) {
      $("hotkeyHint").textContent = "That key can't be used. Try a letter or function key.";
      return;
    }
    const res = await api.set_hotkey(combo);
    if (res.ok) {
      settings.hotkey = combo;
      endHotkeyCapture();
    } else {
      $("hotkeyHint").textContent = res.error;
    }
  });
}

// ---------- run state ----------

function statusText(s) {
  switch (s.state) {
    case "countdown": return `Starting in ${Math.ceil(s.remaining)}…`;
    case "running": return `Clicking — ${s.clicks.toLocaleString()} clicks`;
    case "paused": return "Paused while the cursor is over this window";
    case "holding": return `Holding ${settings.button} button`;
    default: return s.clicks > 0 ? `Stopped — ${s.clicks.toLocaleString()} clicks` : warning || "Idle";
  }
}

function renderRunState(s) {
  const running = s.state !== "idle";
  document.body.classList.toggle("locked", running);
  $("start").textContent = running ? "Stop" : "Start";
  $("start").classList.toggle("running", running);
  $("status").textContent = statusText(s);
  $("status").classList.toggle("warn", !running && s.clicks === 0 && !!warning);
}

window.onEngineUpdate = renderRunState;

function bindFooter() {
  $("start").addEventListener("click", () => {
    if ($("start").classList.contains("running")) {
      api.stop();
    } else {
      clearTimeout(saveTimer);
      api.start(payload());
    }
  });
  $("onTop").addEventListener("change", (e) => {
    settings.always_on_top = e.target.checked;
    api.set_always_on_top(e.target.checked);
  });
}

// Clicks that would land on this window are held back so Stop stays clickable.
function bindCursorTracking() {
  const setOver = (over) => {
    if (over === cursorOverApp) return;
    cursorOverApp = over;
    api.set_cursor_over_app(over);
  };
  document.addEventListener("mousemove", () => setOver(true));
  document.documentElement.addEventListener("mouseleave", () => setOver(false));
}

// ---------- startup ----------

async function init() {
  if (api) return;
  api = window.pywebview.api;
  const state = await api.get_state();
  platform = state.platform;
  warning = state.warning;
  settings = state.settings;

  setCps(settings.cps);
  renderSeg($("buttonSeg"), settings.button);
  renderSeg($("typeSeg"), settings.click_type);
  renderHoldMode();
  renderPosition();
  renderLimits();
  renderHotkey();
  $("onTop").checked = settings.always_on_top;
  renderRunState({ state: state.running ? "running" : "idle", clicks: 0 });

  bindSpeed();
  bindSeg($("buttonSeg"), "button");
  bindSeg($("typeSeg"), "click_type");
  bindPosition();
  bindLimits();
  bindHotkey();
  bindFooter();
  bindCursorTracking();
}

window.addEventListener("pywebviewready", init);
if (window.pywebview && window.pywebview.api) init();

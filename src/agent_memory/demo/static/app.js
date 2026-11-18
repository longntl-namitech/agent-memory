"use strict";
// Page script: chat, memory panels, to-do cards, top-bar controls and theme.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("#theme");
  btn.setAttribute("aria-pressed", String(theme === "light"));
  try { localStorage.setItem("theme", theme); } catch (e) { /* storage may be blocked */ }
}

function initTheme() {
  setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  $("#theme").addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}


// ---- T13: chat, memory panels, to-do card. Server text is only ever set with textContent. ----
const COLS = ["none", "full"];
const TODO = "todo";
const PALETTE = 6; // colour slots --k0..--k5; a kind keeps the slot it first appeared with
const slots = new Map();
function slot(kind) {
  if (!slots.has(kind)) slots.set(kind, slots.size % PALETTE);
  return slots.get(kind);
}
const seenNew = new Set();
let busy = false;
let sending = false;
let serverBusy = false;
let acting = false;
let currentMode = "live";

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

async function api(path, body) {
  // Only /api/state is a GET. A body-less POST sends no Content-Type; with a body it is application/json.
  const init = path === "/api/state" ? {} : { method: "POST" };
  if (body !== undefined) { init.headers = { "Content-Type": "application/json" }; init.body = JSON.stringify(body); }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `request failed (${r.status})`);
  return data;
}

let dismissed = null;  // a dismissed server notice stays hidden until its text changes or goes away
let clientNote = false;  // a notice raised by the page itself (failed request) survives render()
function showNotice(text, fromServer) {
  const n = $("#notice");
  if (fromServer) {
    if (!text) dismissed = null;
    if (text && text === dismissed) text = "";
    if (!text && clientNote) return;
    if (text) clientNote = false;
  } else {
    clientNote = !!text;
  }
  $("#notice-text").textContent = text || "";
  n.hidden = !text;
}

function clearClientNotice() {
  if (!clientNote) return;
  clientNote = false;
  $("#notice").hidden = true;
}

function dismissNotice() {
  dismissed = $("#notice-text").textContent;
  $("#notice").hidden = true;
}

function stamp(iso) { return iso.slice(5, 16).replace("T", " "); }

function entryNode(col, e) {
  const row = el("div", "entry kind-row" + (e.new ? " new" : ""));
  row.style.setProperty("--kind", `var(--k${slot(e.kind)})`);
  if (e.new && !seenNew.has(e.id)) { row.classList.add("flash"); seenNew.add(e.id); }
  const body = el("div", "entry-body");
  const head = el("div", "entry-head");
  head.append(el("span", "kind-tag", e.kind.toUpperCase()), el("span", "entry-key", e.key));
  if (e.new) head.append(el("span", "badge", "NEW"));
  head.append(el("time", "entry-time dim", stamp(e.created_at)));
  body.append(head);
  const text = el("div", "entry-text");
  if (e.replaced_from) {
    text.append(el("s", "old dim", e.replaced_from), " ", el("span", "badge quiet", "replaced"), " ");
  }
  text.append(e.text);
  body.append(text);
  const btn = el("button", "btn ghost small", "Forget this");
  btn.type = "button";
  btn.setAttribute("aria-label", `Forget this ${e.key}: ${e.text}`);
  btn.addEventListener("click", () => forget(col, e.id));
  row.append(body, btn);
  return row;
}

function keepScroll(node, fill) {
  const top = node.scrollTop;
  fill();
  node.scrollTop = top;
}

function todoNode(c, t) {
  const row = el("div", "entry kind-row" + (t.done ? " done" : ""));
  row.style.setProperty("--kind", `var(--k${slot(TODO)})`);
  const body = el("div", "entry-body");
  const head = el("div", "entry-head");
  head.append(el("span", "kind-tag", TODO.toUpperCase()), el("span", "entry-key", t.done ? "done" : "open"));
  body.append(head, el("div", "entry-text", t.text));
  const b = el("button", "btn ghost small", "Remove");
  b.type = "button";
  b.setAttribute("aria-label", `Remove from the list: ${t.text}`);
  b.addEventListener("click", () => forget(c, t.key));
  row.append(body, b);
  return row;
}

// The kinds are whatever the snapshot carries (they differ between memory methods), plus the to-do list.
function renderPanel(c, data) {
  if (!document.getElementById(`pane-${c}`)) return; // the no-memory column shows no memory
  const kinds = Object.keys(data.entries);
  const all = kinds.flatMap((k) => data.entries[k].map((e) => ({ ...e, kind: k })));
  // what just changed first, then newest first
  all.sort((x, y) => (y.new - x.new) || y.created_at.localeCompare(x.created_at));
  const legend = $(`#pane-${c}`).closest(".panel").querySelector(".legend");
  legend.replaceChildren(...[...kinds.map((k) => [k, data.entries[k].length]), [TODO, data.todos.length]].map(([k, n]) => {
    const li = el("li", "kind");
    li.style.setProperty("--kind", `var(--k${slot(k)})`);
    li.append(el("span", "kind-dot"), `${k} ${n}`);
    li.firstChild.setAttribute("aria-hidden", "true");
    return li;
  }));
  const pane = $(`#pane-${c}`);
  keepScroll(pane, () => {
    pane.replaceChildren();
    const nodes = [...data.todos.map((t) => todoNode(c, t)), ...all.map((e) => entryNode(c, e))];
    if (!nodes.length) pane.append(el("p", "empty dim", c === "none" ? "Nothing is kept for this assistant" : "Nothing remembered yet"));
    else pane.append(...nodes);
  });
  $(`#seen-${c}`).textContent = data.recalled || "(nothing was recalled)";
}

function render(snap) {
  $("#sim-date").textContent = snap.date;
  $("#sim-date").setAttribute("datetime", snap.date.split(" ").pop());
  $("#mode-live").setAttribute("aria-pressed", String(snap.mode === "live"));
  $("#mode-replay").setAttribute("aria-pressed", String(snap.mode === "replay"));
  $("#tokens-cap").textContent = `Token cap ${snap.cap.toLocaleString()} per column`;
  $("#tokens-none").textContent = `${snap.columns.none.tokens.toLocaleString()} tokens`;
  $("#tokens-full").textContent = `${snap.columns.full.tokens.toLocaleString()} tokens`;
  showNotice(snap.notice, true);
  currentMode = snap.mode;
  const labels = { live: "Live model", replay: "Replay, offline", warmup: "Warm-up, recording" };
  $("#mode-text").textContent = labels[snap.mode] || snap.mode;
  $("#mode-status").classList.toggle("replay", snap.mode === "replay");
  for (const c of COLS) {
    const err = $(`#error-${c}`);
    err.textContent = snap.columns[c].error || "";
    err.hidden = !snap.columns[c].error;
  }
  const chips = $("#chips");
  if (!chips.children.length) {
    for (const p of snap.prompts.script) {
      const b = el("button", "", p);
      b.type = "button";
      b.addEventListener("click", () => send(p));
      chips.append(b);
    }
  }
  for (const c of COLS) { renderPanel(c, snap.columns[c]); }
  serverBusy = snap.busy;
  setBusy(snap.busy || sending || acting);
  pollWhileBusy(snap.busy);
}

// After a reload mid-turn the server may still be busy: poll (1s, then 3s after a failure), one poll at a
// time. After 5 failures in a row give up and re-enable the controls so the page is not stuck.
let polling = false;
let pollFails = 0;
function pollWhileBusy(isBusy) {
  if (!isBusy) { pollFails = 0; return; }
  if (polling || sending) return;
  polling = true;
  setTimeout(async () => {
    polling = false;
    if (sending) return;
    try {
      const snap = await api("/api/state");
      pollFails = 0;
      render(snap);
    } catch (e) {
      if (++pollFails >= 5) { pollFails = 0; showNotice(e.message); setBusy(false); return; }
      pollWhileBusy(true);
    }
  }, pollFails ? 3000 : 1000);
}

function setBusy(v) {
  busy = v;
  for (const id of ["send-btn", "advance", "reflect", "new-chat", "reset", "wipe"]) $(`#${id}`).disabled = v;
  // the active mode button is disabled too, so clicking it cannot do anything
  $("#mode-live").disabled = v || currentMode === "live";
  $("#mode-replay").disabled = v || currentMode === "replay";
  $$("#chips button").forEach((b) => { b.disabled = v; });
}

async function forget(c, id) {
  clearClientNotice();
  try { render(await api("/api/forget", { column: c, entry_id: id })); } catch (e) { showNotice(e.message); }
}

function addMsg(c, text, cls) {
  const m = el("div", "msg" + (cls ? " " + cls : ""), text);
  $(`#transcript-${c}`).append(m);
  m.scrollIntoView({ block: "end" });
  return m;
}

function parseSSE(buf, onEvent) {
  let i;
  while ((i = buf.indexOf("\n\n")) >= 0) {
    const block = buf.slice(0, i);
    buf = buf.slice(i + 2);
    let name = "message", data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (data) onEvent(name, JSON.parse(data));
  }
  return buf;
}

async function send(text) {
  text = text.trim();
  if (!text || busy) return;
  clearClientNotice();
  disarmWipe();
  sending = true;
  setBusy(true);
  const bubbles = {};
  // Deltas fill a pending bubble inside a transcript that is aria-busy, so a screen reader hears the
  // whole message once, when the turn is complete, not every chunk.
  for (const c of COLS) {
    $(`#transcript-${c}`).setAttribute("aria-busy", "true");
    addMsg(c, text, "user");
    const b = addMsg(c, "", "assistant pending");
    b.append(el("span", "dots", "Thinking"));
    bubbles[c] = b;
  }
  $("#input").value = "";
  const got = {};
  let gotSnapshot = false;
  const onEvent = (name, d) => {
    if (name === "delta") {
      const b = bubbles[d.column];
      if (!got[d.column]) { b.replaceChildren(); b.classList.remove("pending"); got[d.column] = true; }
      b.append(d.text);
    } else if (name === "error") {
      if (d.column) {
        const b = bubbles[d.column];
        if (!got[d.column]) { b.replaceChildren(); b.classList.remove("pending"); got[d.column] = true; }
        b.classList.add("error");
        b.append(got[d.column] && b.textContent ? ` (${d.message})` : d.message);
      } else showNotice(d.message);
    } else if (name === "snapshot") { gotSnapshot = true; render(d); }
  };
  try {
    const r = await fetch("/api/turn", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `request failed (${r.status})`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf = parseSSE(buf + dec.decode(value, { stream: true }), onEvent);
    }
  } catch (e) {
    showNotice(e.message);
  } finally {
    sending = false;
    if (!gotSnapshot) {  // stream ended or dropped without a snapshot: ask the server for the state
      try { render(await api("/api/state")); } catch (e) { showNotice(e.message); }
    }
    for (const c of COLS) {
      const b = bubbles[c];
      if (b.classList.contains("pending")) { b.replaceChildren(); b.classList.remove("pending"); b.classList.add("error"); b.textContent = "No reply"; }
      $(`#transcript-${c}`).setAttribute("aria-busy", "false");
    }
    setBusy(serverBusy);
    pollWhileBusy(serverBusy);
    $("#input").focus();
  }
}

// The "what the assistant saw" overlay: a disclosure button, Escape closes it.
function initSeen(c) {
  if (!document.getElementById(`seen-toggle-${c}`)) return;
  const toggle = $(`#seen-toggle-${c}`);
  // Narrow windows get a short visible label so the legend and the toggle fit on one row; the accessible
  // name stays the full sentence and aria-expanded carries the state.
  const compact = window.matchMedia("(max-width: 1279px)");
  const label = () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    const full = `${open ? "Hide" : "Show"} what the assistant saw`;
    toggle.setAttribute("aria-label", full);
    toggle.textContent = compact.matches ? "What it saw" : full;
  };
  label();
  compact.addEventListener("change", label);
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    label();
    $(`#seen-${c}`).hidden = !open;
  });
  const seen = $(`#seen-${c}`);
  seen.tabIndex = 0;
  const close = (ev) => {
    if (ev.key !== "Escape" || seen.hidden) return;
    ev.preventDefault();
    toggle.click();
    toggle.focus();
  };
  toggle.addEventListener("keydown", close);
  seen.addEventListener("keydown", close);
}

initTheme();
// One request at a time: every control is disabled while it runs and is re-enabled whether it works or not.
async function act(path, body, after) {
  if (busy) return;
  clearClientNotice();
  if (path !== "/api/wipe") disarmWipe();
  acting = true;
  setBusy(true);
  try {
    const snap = await api(path, body);
    if (after) after();
    render(snap);
  } catch (e) {
    showNotice(e.message);
  } finally {
    acting = false;
    setBusy(serverBusy || sending);
    pollWhileBusy(serverBusy);
  }
}

function clearTranscripts() { for (const c of COLS) $(`#transcript-${c}`).replaceChildren(); }

let wipeTimer = null;
function disarmWipe() {
  clearTimeout(wipeTimer);
  wipeTimer = null;
  const w = $("#wipe");
  w.textContent = "Wipe all data";
  w.classList.remove("danger");
  $("#wipe-status").textContent = "";
}

// A mode switch rebuilds the memory from the user's messages only, so the old transcripts no longer match.
$("#mode-live").addEventListener("click", () => act("/api/mode", { mode: "live" }, clearTranscripts));
$("#mode-replay").addEventListener("click", () => act("/api/mode", { mode: "replay" }, clearTranscripts));
$("#wipe").addEventListener("blur", disarmWipe);
$("#advance").addEventListener("click", () => act("/api/advance"));
$("#reflect").addEventListener("click", () => act("/api/reflect"));
// The assistants only see the current message plus memory, so clearing the chat is faithful: memory stays.
$("#new-chat").addEventListener("click", () => { clearTranscripts(); $("#input").focus(); });
$("#reset").addEventListener("click", () => act("/api/reset", undefined, clearTranscripts));
$("#wipe").addEventListener("click", () => {
  if (wipeTimer === null) {  // first click arms, a second click within 5 seconds wipes; no browser dialogs
    const w = $("#wipe");
    w.textContent = "Confirm wipe";
    w.classList.add("danger");
    $("#wipe-status").textContent = "Press again within 5 seconds to wipe all data";
    wipeTimer = setTimeout(disarmWipe, 5000);
    return;
  }
  disarmWipe();
  act("/api/wipe", undefined, clearTranscripts);
});
$("#notice-close").addEventListener("click", dismissNotice);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !ev.defaultPrevented && !$("#notice").hidden) dismissNotice();
});
COLS.forEach(initSeen);
$("#send").addEventListener("submit", (ev) => { ev.preventDefault(); send($("#input").value); });
api("/api/state").then(render).catch((e) => showNotice(e.message));

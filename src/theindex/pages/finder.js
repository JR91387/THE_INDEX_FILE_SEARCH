/* Ctrl-K finder. theIndexFinder({served, token, finder}) wires the keys; all data goes in with textContent. */
function theIndexFinder(D) {
"use strict";
var CSS = ".ixf{position:fixed;inset:0;z-index:50;display:flex;justify-content:center;align-items:flex-start;" +
  "padding:12vh 12px 0;background:rgba(0,0,0,.4)}.ixf[hidden]{display:none}" +
  ".ixf-box{width:min(640px,100%);max-height:70vh;display:flex;flex-direction:column;background:var(--bg,Canvas);" +
  "color:var(--fg,CanvasText);border:1px solid var(--line,#8886);border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.35)}" +
  ".ixf input{margin:10px;padding:8px 10px;font:inherit;color:inherit;background:var(--card,Field);" +
  "border:1px solid var(--line,#8886);border-radius:6px}" +
  ".ixf ul{list-style:none;margin:0;padding:0 6px;overflow-y:auto}" +
  ".ixf li{padding:6px 8px;border-radius:6px;cursor:pointer}" +
  ".ixf li[aria-selected=true]{background:var(--card,#8882);outline:1px solid var(--link,#1a56a0)}" +
  ".ixf a{color:inherit;text-decoration:none;display:block}" +
  ".ixf .p{font-size:.82rem;color:var(--mute,GrayText);overflow-wrap:anywhere;user-select:text}" +
  ".ixf .s{padding:6px 12px 10px;font-size:.82rem;color:var(--mute,GrayText)}";
var MAX_SHOWN = 30, DEBOUNCE = 120, KINDS = { p: "project", d: "folder", f: "document" };
var WORD = /[\p{L}\p{N}]+/gu;
var rows = D.finder || [], cache = [];
var useApi = location.protocol !== "file:" && !!D.served;
var root, input, list, status, prevFocus, items = [], sel = -1, timer = null, seq = 0;

function words(s) { return String(s || "").toLowerCase().match(WORD) || []; }
function fields(i) {
  if (!cache[i]) cache[i] = [words(rows[i][3]), words(rows[i][4]), words(rows[i][2])];
  return cache[i];
}
function best(fs, qw) {
  for (var f = 0; f < fs.length; f++)
    for (var k = 0; k < fs[f].length; k++) if (fs[f][k].indexOf(qw) === 0) return f;
  return -1;
}
function localSearch(q) {
  var qs = words(q), out = [];
  if (!qs.length) return out;
  rows.forEach(function (r, i) {
    var fs = fields(i), score = 0;
    for (var j = 0; j < qs.length; j++) {
      var f = best(fs, qs[j]);
      if (f < 0) return;
      score += f;
    }
    out.push({ score: score, kind: "pdf".indexOf(r[0]), len: r[2].length,
      item: { type: r[0], device: r[1], path: r[2], name: r[3], title: r[4] } });
  });
  out.sort(function (a, b) { return a.score - b.score || a.kind - b.kind || a.len - b.len; });
  return out.slice(0, MAX_SHOWN).map(function (o) { return o.item; });
}
function fileUrl(p) {
  var s = p.replace(/\\/g, "/");
  if (s.charAt(0) !== "/") s = "/" + s;
  return "file://" + encodeURI(s).replace(/#/g, "%23").replace(/\?/g, "%3F");
}
function kindOf(r) {
  if (r.type === "p") return KINDS.p;
  if (r.type === "d" || (r.type === "dir" && !r.is_project)) return KINDS.d;
  return r.type === "dir" ? KINDS.p : KINDS.f;
}
function show(results, message) {
  list.textContent = "";
  items = results;
  sel = results.length ? 0 : -1;
  results.forEach(function (r, i) {
    var li = document.createElement("li"), host = document.createElement(useApi ? "div" : "a");
    var head = document.createElement("div"), path = document.createElement("div");
    li.id = "ixf-" + i;
    li.setAttribute("role", "option");
    head.textContent = (r.title || r.name || r.path) + " (" + kindOf(r) + ")";
    path.className = "p";
    path.textContent = (r.device ? r.device + ":" : "") + r.path;
    if (!useApi) { host.href = fileUrl(r.path); host.tabIndex = -1; }
    host.appendChild(head);
    host.appendChild(path);
    li.appendChild(host);
    li.addEventListener("click", function () { sel = i; choose(); });
    list.appendChild(li);
  });
  mark();
  status.textContent = message || (results.length ? results.length + " results" : (input.value.trim() ? "Nothing found" : ""));
}
function mark() {
  Array.prototype.forEach.call(list.children, function (li, i) {
    li.setAttribute("aria-selected", i === sel ? "true" : "false");
    if (i === sel) { li.scrollIntoView({ block: "nearest" }); input.setAttribute("aria-activedescendant", li.id); }
  });
  if (sel < 0) input.removeAttribute("aria-activedescendant");
}
function copy(text) {
  var done = function () { status.textContent = "copied"; };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
  } else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  var t = document.createElement("textarea");
  t.value = text;
  t.style.position = "fixed";
  t.style.opacity = "0";
  document.body.appendChild(t);
  t.select();
  try { if (document.execCommand("copy")) done(); } catch (e) { status.textContent = "copy failed: select the path"; }
  document.body.removeChild(t);
  input.focus();
}
function choose() {
  if (sel < 0 || !items[sel]) return;
  if (useApi) copy(items[sel].path);
  else list.children[sel].firstChild.click();
}
function query(q) {
  if (!useApi) return show(localSearch(q));
  if (!q.trim()) return show([]);
  var mine = ++seq;
  fetch("/api/find?limit=20&q=" + encodeURIComponent(q), { headers: { "X-The-Index-Token": D.token || "" } })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      if (mine !== seq) return;
      if (j.error) return show([], String(j.error));
      show(j.results.map(function (r) {
        return { type: r.type, device: r.device, path: r.path, name: r.name, title: r.title, is_project: r.is_project };
      }), j.more ? j.results.length + " shown, " + j.more + " more: add words" : "");
    })
    .catch(function () { if (mine === seq) show([], "Search failed"); });
}
function onInput() {
  clearTimeout(timer);
  timer = setTimeout(function () { query(input.value); }, useApi ? DEBOUNCE : 0);
}
function open() {
  if (!root.hidden) return;
  prevFocus = document.activeElement;
  root.hidden = false;
  input.value = "";
  show([]);
  input.focus();
}
function close() {
  if (root.hidden) return;
  root.hidden = true;
  seq++;
  if (prevFocus && prevFocus.focus) prevFocus.focus();
}
function move(d) {
  if (!items.length) return;
  sel = (sel + d + items.length) % items.length;
  mark();
}
function typing(e) {
  var t = e.target, tag = t && t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable);
}
function onKey(e) {
  var k = e.key;
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (k === "k" || k === "K")) { e.preventDefault(); return open(); }
  if (root.hidden) {
    if (k === "/" && !e.ctrlKey && !e.metaKey && !e.altKey && !typing(e)) { e.preventDefault(); open(); }
    return;
  }
  if (k === "Escape") { e.preventDefault(); close(); }
  else if (k === "ArrowDown") { e.preventDefault(); move(1); }
  else if (k === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (k === "Enter") { e.preventDefault(); choose(); }
  else if (k === "Tab") { e.preventDefault(); input.focus(); }     /* focus trap: the box has one stop */
}
function build() {
  var style = document.createElement("style"), box = document.createElement("div");
  style.textContent = CSS;
  document.head.appendChild(style);
  root = document.createElement("div");
  root.className = "ixf";
  root.hidden = true;
  box.className = "ixf-box";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Search THE INDEX");
  input = document.createElement("input");
  input.type = "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = "Find folders, projects and documents";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-label", "Search folders, projects and documents");
  input.setAttribute("aria-controls", "ixf-list");
  input.setAttribute("aria-expanded", "true");
  list = document.createElement("ul");
  list.id = "ixf-list";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Results");
  status = document.createElement("div");
  status.className = "s";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  [input, list, status].forEach(function (n) { box.appendChild(n); });
  root.appendChild(box);
  document.body.appendChild(root);
  root.addEventListener("mousedown", function (e) { if (e.target === root) close(); });
  input.addEventListener("input", onInput);
}
build();
document.addEventListener("keydown", onKey);
}

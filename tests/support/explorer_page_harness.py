"""The composition tests' Node harness (#146): the real Explorer page, booted as it starts in a browser.

Only the outside is fake: the DOM, fetch, frames, timers and the vendored 3D graph's boundary. The page starts
at ``?diagnostics``; a test drives it as the listener and the server would (typing, clicking, answering
requests) and observes it through its diagnostics seam, the fake DOM and the requests it made. No page
function is called and no page variable is read or written.
"""
from pathlib import Path
from tests.support.explorer_app_bundle import explorer_app_script


ROOT = Path(__file__).resolve().parents[2]

ASSETS = tuple(explorer_app_script(ROOT / package / 'frameworks/explorer/assets/app.js')
               for package in ('music_explorer', 'music_analyzer'))


FAKE_DOM = r'''
// --- The DOM: plain elements with the parts the page's views use. -------------------------------
let elementCount = 0;
function element(tag) {
  const listeners = {};
  const node = {
    tagName: String(tag).toUpperCase(), id: '', children: [], attributes: {}, style: {},
    value: '', ownText: '', hidden: false, disabled: false, className: '', parentElement: null,
    clientWidth: 800, clientHeight: 600, serial: ++elementCount,
    get textContent() { return this.ownText + this.children.map(child => child.textContent || '').join(''); },
    set textContent(value) { this.ownText = String(value); this.children = []; },
    get innerText() { return this.hidden ? '' : [this.ownText, ...this.children.map(child => child.innerText || '')].join(' '); },
    set innerHTML(value) { this.ownText = String(value); this.children = []; },
    get options() { return this.children.filter(child => child.tagName === 'OPTION'); },
    get selectedOptions() { return this.options.filter(option => option.selected); },
    classList: {
      values: new Set(),
      add(...names) { for (const name of names) this.values.add(name); },
      remove(...names) { for (const name of names) this.values.delete(name); },
      toggle(name, on) { const next = on ?? !this.values.has(name); if (next) this.values.add(name); else this.values.delete(name); return next; },
      contains(name) { return this.values.has(name); },
    },
    append(...nodes) {
      for (const child of nodes) {
        const node = typeof child === 'string' ? textNode(child) : child;
        node.remove?.(); node.parentElement = this; this.children.push(node);
      }
    },
    appendChild(child) { this.append(child); return child; },
    replaceChild(fresh, old) { old.replaceWith(fresh); return old; },
    prepend(...nodes) { const rest = this.children; this.children = []; this.append(...nodes); this.children.push(...rest); },
    replaceChildren(...nodes) { for (const child of this.children) child.parentElement = null; this.children = []; this.ownText = ''; this.append(...nodes); },
    replaceWith(...nodes) {
      const parent = this.parentElement; if (!parent) return;
      const at = parent.children.indexOf(this);
      const fresh = nodes.map(child => typeof child === 'string' ? textNode(child) : child);
      for (const child of fresh) { child.remove?.(); child.parentElement = parent; }
      parent.children.splice(at, 1, ...fresh); this.parentElement = null;
    },
    remove() { const parent = this.parentElement; if (parent) parent.children = parent.children.filter(child => child !== this); this.parentElement = null; },
    setAttribute(key, value) { this.attributes[key] = String(value); if (key === 'id') this.id = String(value); },
    getAttribute(key) { return this.attributes[key] ?? null; },
    hasAttribute(key) { return key in this.attributes; },
    removeAttribute(key) { delete this.attributes[key]; },
    toggleAttribute(key, on) { const next = on ?? !(key in this.attributes); if (next) this.attributes[key] = ''; else delete this.attributes[key]; return next; },
    addEventListener(type, listener) { (listeners[type] ??= []).push(listener); },
    removeEventListener(type, listener) { listeners[type] = (listeners[type] || []).filter(item => item !== listener); },
    dispatch(type, detail = {}) {
      const event = {type, target: this, currentTarget: this, isTrusted: true, preventDefault() {}, stopPropagation() {}, ...detail};
      this['on' + type]?.(event);
      for (const listener of [...(listeners[type] || [])]) listener(event);
      return event;
    },
    getBoundingClientRect() { return {width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600}; },
    getContext() { return canvasContext; },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) { return walk(this).filter(node => node !== this && matches(node, selector)); },
    matches(selector) { return matches(this, selector); },
    closest(selector) { for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node; return null; },
    focus() {}, blur() {}, scrollIntoView() {}, click() { return this.dispatch('click'); },
  };
  // As in a browser, dataset.trackId is the data-track-id attribute.
  node.dataset = new Proxy({}, {set(values, key, value) {
    values[key] = String(value); node.attributes['data-' + key.replace(/[A-Z]/g, c => '-' + c.toLowerCase())] = String(value); return true;
  }});
  return node;
}
function textNode(value) { const node = element('#text'); node.ownText = String(value); return node; }
function walk(root) { return [root, ...root.children.flatMap(walk)]; }
// Enough of CSS selectors for the page: tag, #id, .class and [attribute], and one descendant step.
function matches(node, selector) {
  const parts = selector.trim().split(/\s+/);
  if (parts.length > 1) {
    if (!matches(node, parts.at(-1))) return false;
    const ancestor = parts.slice(0, -1).join(' ');
    for (let up = node.parentElement; up; up = up.parentElement) if (matches(up, ancestor)) return true;
    return false;
  }
  const simple = /^([a-z0-9]*)((?:[#.][\w-]+|\[[^\]]+\])*)$/i.exec(selector);
  if (!simple) return false;
  if (simple[1] && node.tagName !== simple[1].toUpperCase()) return false;
  for (const [part] of simple[2].matchAll(/[#.][\w-]+|\[[^\]]+\]/g)) {
    if (part[0] === '#' && node.id !== part.slice(1)) return false;
    if (part[0] === '.' && !String(node.className).split(/\s+/).includes(part.slice(1)) && !node.classList.contains(part.slice(1))) return false;
    if (part[0] === '[') {
      const [key, value] = part.slice(1, -1).split('=');
      if (!(key in node.attributes)) return false;
      if (value !== undefined && node.attributes[key] !== value.replace(/^['"]|['"]$/g, '')) return false;
    }
  }
  return true;
}
const canvasContext = {clearRect() {}, fillRect() {}, beginPath() {}, fill() {}, stroke() {}, moveTo() {}, lineTo() {},
  arc() {}, save() {}, restore() {}, setLineDash() {}, fillText() {}, measureText: () => ({width: 10})};
const body = element('body');
for (const [id, tag] of [['tracks', 'table'], ['track-search', 'input'], ['undo', 'button'], ['reset', 'button'],
  ['controls', 'div'], ['detail', 'section'], ['graph-load-status', 'div'], ['library-loading', 'div'],
  ['loading-surface', 'div'], ['loading-status', 'div'], ['loading-error', 'div'], ['loading-retry', 'button'],
  ['graph3d', 'div'], ['map', 'canvas'], ['mood-strip', 'canvas'], ['mood-strip-picker', 'input'], ['mood-strip-value', 'output']]) {
  const node = element(tag); node.id = id; body.append(node);
}
body.querySelector('#tracks').append(element('tbody'));
const documentListeners = {};
const document = {body, createElement: element, createTextNode: textNode,
  getElementById: id => walk(body).find(node => node.id === id) || null,
  querySelector: selector => body.querySelector(selector), querySelectorAll: selector => body.querySelectorAll(selector),
  addEventListener(type, listener) { (documentListeners[type] ??= []).push(listener); }, removeEventListener() {}};
const byId = id => document.getElementById(id);

'''


PAGE = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

''' + FAKE_DOM + r'''
// --- Time: frames and timers run only when a test says so. -----------------------------------------
let clock = 0, timerId = 0;
const frames = [], timers = new Map();
function frame() { clock += 16; for (const callback of frames.splice(0)) callback(clock); }
async function settle(rounds = 4) { for (let round = 0; round < rounds; round++) { await flush(); frame(); } await flush(); }
async function flush() { for (let i = 0; i < 60; i++) await Promise.resolve(); }
// Run frames until the page's camera arc has finished, as its diagnostics seam reports it.
async function untilCameraSettles(limit = 400) {
  for (let count = 0; count < limit; count++) { await flush(); if (!context.explorerDiagnostics.snapshot().cameraFocusActive) return; frame(); }
  assert.fail('the camera arc did not finish within ' + limit + ' frames');
}
async function advance(ms) { clock += ms; for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.callback(); } await flush(); }

// --- The vendored 3D graph's boundary: a scene that mounts what the page gives it. ----------------
class Scene {
  constructor() { this.children = []; }
  add(child) { this.children.push(child); child.parent = this; }
  remove(child) { this.children = this.children.filter(item => item !== child); child.parent = null; }
}
const scene = new Scene();
class Geometry { constructor(radius) { this.parameters = {radius}; } dispose() { this.disposed = true; } }
class Material { constructor(props = {}) { Object.assign(this, props); } dispose() { this.disposed = true; } }
class Mesh {
  constructor(geometry, material) { this.geometry = geometry; this.material = material; this.userData = {};
    this.position = {x: 0, y: 0, z: 0, set(x, y, z) { Object.assign(this, {x, y, z}); }};
    this.scale = {setScalar(value) { this.value = value; }, set(x, y, z) { Object.assign(this, {x, y, z}); }}; }
}
const camera = {fov: 50, position: {x: 500, y: 400, z: 300}, up: {x: 0, y: 1, z: 0}};
const controls = {target: {x: 0, y: 0, z: 0}, listeners: {}, addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); },
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(item => item !== fn); }, update() {}};
const cameraMoves = [];
let mounted = {nodes: [], links: []}, nodeClick = null, nodeSize = null, mounts = 0;
const graph = new Proxy({}, {get(_target, key) {
  if (key === 'scene') return () => scene;
  if (key === 'camera') return () => camera;
  if (key === 'controls') return () => controls;
  if (key === 'renderer') return () => ({domElement: byId('graph3d'), render() {}, getContext: () => ({})});
  if (key === 'graph2ScreenCoords') return () => ({x: 400, y: 300});
  if (key === 'graphData') return data => {
    if (!data) return mounted;
    mounted = data; mounts += 1;
    scene.children = scene.children.filter(child => !child.userData?.trackId);
    for (const node of data.nodes) {
      const mesh = new Mesh(new Geometry(4), new Material()); mesh.userData.trackId = node.id; mesh.__graphObjType = 'node';
      mesh.position.set(node.fx, node.fy, node.fz); scene.add(mesh);
    }
    return graph;
  };
  if (key === 'cameraPosition') return (position, target, duration) => {
    if (!position) return {...camera.position};
    cameraMoves.push({position: {...position}, target: {...target}, duration, at: clock});
    Object.assign(camera.position, position); if (target) Object.assign(controls.target, target);
    return graph;
  };
  if (key === 'onNodeClick') return handler => { nodeClick = handler; return graph; };
  if (key === 'nodeVal') return size => { nodeSize = size; return graph; };
  return () => graph;
}});

// --- The server: each request waits until the test answers it, unless a route answers by itself. --
const requests = [];
const routes = {};
function answer(body, status = 200) {
  return {ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body)};
}
function request(path, index = 0) {
  const found = requests.filter(item => item.path === path)[index];
  assert.ok(found, `the page asked for ${path} #${index}; it asked for ${requests.map(item => item.path).join(', ')}`);
  return found;
}
function fetch(path, options = {}) {
  const url = new URL(String(path), 'http://127.0.0.1/');
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  const item = {path: url.pathname, url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null,
    respond(body, status) { resolve(answer(body, status)); }, fail(error = new Error('offline')) { reject(error); }};
  requests.push(item);
  const route = routes[url.pathname] || (url.pathname.startsWith('/api/tracks/') && url.pathname !== '/api/tracks/summary' && routes['/api/tracks/<id>']);
  if (route) Promise.resolve().then(() => route(item));
  return promise;
}

// --- Synthetic library: tracks placed on the mood axes, served as the indexed graph. --------------
function track(id, x = 0.25, y = -0.4, z = 0.6) { return {id, title: 'Track ' + id, artist: 'Public synthetic', x, y, z}; }
function graphBody(tracks, {links = [], mood = 'calm'} = {}) {
  return {dto_version: 'mood-axis-graph-indexed-v1', selected_mood: mood, available_moods: [mood],
    axis: [{key: 'x', label: 'Valence', scale: 'unit'}, {key: 'y', label: 'Arousal', scale: 'unit'}, {key: 'z', label: 'BPM', scale: 'bpm'}],
    nodes: tracks.map(t => [t.id, t.title, t.x, t.x, t.y, t.y, 120, t.z, null, 0.5, [], []]),
    links, unpositioned: [], genre_labels: [], reason_text: [], explanation_table: [], provenance_table: [],
    metadata: {graph_status: {state: 'ready'}}};
}
function summaryBody(tracks) {
  return {tracks: tracks.map(t => ({handle: t.id, title: t.title, artist: t.artist})), metadata: {track_count: tracks.length}, next_cursor: null};
}
const accepted = (id, {epoch = 1, history = []} = {}) => ({current_track_id: id, selection_epoch: epoch, history, selection_accepted: true});
const detailBody = id => ({handle: id, metadata: {common: [['title', 'Track ' + id]], tags: []}, fields: {}});

// --- The page, booted at ?diagnostics. ------------------------------------------------------------
const storage = new Map();
const context = vm.createContext({console, URL, URLSearchParams, Event: class { constructor(type) { this.type = type; } },
  document, location: {search: '?diagnostics', href: 'http://127.0.0.1/?diagnostics'},
  sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value))},
  requestAnimationFrame: callback => { frames.push(callback); return frames.length; }, cancelAnimationFrame() {},
  setTimeout: (callback, delay = 0) => { const id = ++timerId; timers.set(id, {callback, at: clock + delay}); return id; },
  clearTimeout: id => timers.delete(id), performance: {now: () => clock},
  ResizeObserver: class { observe() {} disconnect() {} }, ForceGraph3D: () => () => graph, fetch});
function boot() { vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context, {filename: process.argv[1]}); return context.explorerDiagnostics; }

// --- The listener's actions. -----------------------------------------------------------------------
function rows() { return document.querySelectorAll('#tracks tbody tr'); }
function row(id) { const found = rows().find(item => item.dataset.trackId === id); assert.ok(found, 'a row for ' + id); return found; }
async function search(text) { const box = byId('track-search'); box.value = text; box.dispatch('input'); await advance(1000); }
async function chooseRow(id) { row(id).querySelector('button').click(); await flush(); }
async function pickNode(id) { const node = mounted.nodes.find(item => item.id === id); assert.ok(node, 'a mounted node ' + id); const pending = nodeClick(node); await flush(); return pending; }
async function press(id) { byId(id).click(); await flush(); }
function orbit() { for (const listener of controls.listeners.start || []) listener({type: 'start'}); }
'''

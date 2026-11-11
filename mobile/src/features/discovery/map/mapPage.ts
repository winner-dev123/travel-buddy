/**
 * The Companions map page (ADR-0030): MapLibre GL JS with OpenFreeMap vector tiles inside a
 * WebView, a radar sweep while searching, and a pin per traveller found.
 *
 * Data reaches the page only through `tbMap.apply(command)` as JSON. Names are set with
 * `textContent`, never parsed as HTML. The page can't navigate, ask for the device location or
 * reach any host but the CDN and the tile server (Content-Security-Policy below). MapLibre is
 * pinned and checked with Subresource Integrity.
 */

export const MAPLIBRE_VERSION = '5.24.0';
const CDN = `https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VERSION}/dist`;
export const MAPLIBRE_SCRIPT = {
  url: `${CDN}/maplibre-gl.js`,
  integrity: 'sha384-5+cfbwT0iiub6VsQAdn6yz16nr6sDiQoHx6tm4O8OVYXHYOxcffFmCJBL0dgdvGp',
};
export const MAPLIBRE_STYLESHEET = {
  url: `${CDN}/maplibre-gl.css`,
  integrity: 'sha384-uTttxo/aOKbdE5RlD/SPzSDoDmNvGlUYPjONi2MN/b7c9HPSvW07OIuyP7uL6jxK',
};
export const TILE_HOST = 'https://tiles.openfreemap.org';
/** OpenFreeMap styles: free, keyless, OpenStreetMap data (attribution shown by the map). */
export const MAP_STYLES = {
  dark: `${TILE_HOST}/styles/dark`,
  light: `${TILE_HOST}/styles/positron`,
} as const;
/** One turn of the radar beam. */
export const SWEEP_MS = 2400;
/** The page reports `error` when the map hasn't drawn after this long (offline, no WebGL). */
const LOAD_TIMEOUT_MS = 20000;
/** The traveller sits this far below the middle, clear of the place chip on top of the map. */
const TOP_INSET_PX = 48;

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface MapPin {
  id: string;
  name: string;
  /** Shown when there is no photo. */
  initial: string;
  avatarUrl: string | null;
  lat: number;
  lng: number;
  /** Read by screen readers inside the map, e.g. "Open profile: Mika". */
  label: string;
}

export type MapCommand =
  /** Centre on the traveller; zoom so a circle of `radiusM` fills the radar. */
  | { type: 'view'; center: GeoPoint; radiusM: number; animate: boolean }
  | { type: 'scan' }
  /** While scanning, each pin appears as the beam passes it; otherwise at once. */
  | { type: 'pins'; pins: MapPin[] }
  | { type: 'stop' }
  | { type: 'clear' };

export type MapMessage =
  | { type: 'ready' }
  | { type: 'loaded' }
  | { type: 'revealed' }
  | { type: 'error'; reason: string }
  | { type: 'open'; id: string };

export interface MapPageOptions {
  scheme: 'light' | 'dark';
  colors: {
    background: string;
    primary: string;
    onPrimary: string;
    textPrimary: string;
    /** Behind pin names. */
    scrim: string;
  };
  reduceMotion: boolean;
}

/** JavaScript for `WebView.injectJavaScript`. */
export function commandScript(command: MapCommand): string {
  return `window.tbMap&&window.tbMap.apply(${JSON.stringify(command)});true;`;
}

/** A message from the page, or null for anything unexpected. */
export function parseMapMessage(data: string): MapMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null) return null;
  const message = value as Record<string, unknown>;
  switch (message.type) {
    case 'ready':
    case 'loaded':
    case 'revealed':
      return { type: message.type };
    case 'error':
      return { type: 'error', reason: typeof message.reason === 'string' ? message.reason : '' };
    case 'open':
      return typeof message.id === 'string' && message.id.length > 0 && message.id.length <= 64
        ? { type: 'open', id: message.id }
        : null;
    default:
      return null;
  }
}

function rgb(hex: string): string {
  const value = hex.replace('#', '');
  const full =
    value.length === 3
      ? value
          .split('')
          .map((c) => c + c)
          .join('')
      : value;
  const n = parseInt(full.slice(0, 6), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

/** JSON that is safe inside an inline <script>. */
function scriptJson(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026');
}

const CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'unsafe-inline' https://cdn.jsdelivr.net",
  "style-src 'unsafe-inline' https://cdn.jsdelivr.net",
  `connect-src ${TILE_HOST}`,
  'img-src https: data: blob:',
  'worker-src blob:',
  'child-src blob:',
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

export function buildMapPage(options: MapPageOptions): string {
  const { colors } = options;
  const config = {
    styleUrl: MAP_STYLES[options.scheme],
    background: colors.background,
    reduceMotion: options.reduceMotion,
    sweepMs: SWEEP_MS,
    loadTimeoutMs: LOAD_TIMEOUT_MS,
    topInset: TOP_INSET_PX,
  };
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta http-equiv="Content-Security-Policy" content="${CONTENT_SECURITY_POLICY}">
<meta name="referrer" content="no-referrer">
<link rel="stylesheet" href="${MAPLIBRE_STYLESHEET.url}" integrity="${MAPLIBRE_STYLESHEET.integrity}" crossorigin="anonymous">
<style>
:root {
  --bg: ${colors.background};
  --gold: ${colors.primary};
  --gold-rgb: ${rgb(colors.primary)};
  --on-gold: ${colors.onPrimary};
  --text: ${colors.textPrimary};
  --scrim: ${colors.scrim};
  --sweep: ${SWEEP_MS}ms;
}
html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: var(--bg); }
body { font-family: system-ui, -apple-system, Roboto, sans-serif; -webkit-tap-highlight-color: transparent; -webkit-user-select: none; user-select: none; }
.maplibregl-ctrl-attrib.maplibregl-compact { background: var(--scrim); color: var(--text); margin: 0 8px 8px 0; }
.maplibregl-ctrl-attrib-inner { font-size: 10px; line-height: 14px; }
.maplibregl-ctrl-attrib a { color: var(--text); }
.maplibregl-ctrl-attrib-button { filter: invert(1); }
.you { position: relative; width: 0; height: 0; pointer-events: none; }
.you .dot { position: absolute; left: -8px; top: -8px; width: 16px; height: 16px; border-radius: 50%; background: var(--gold);
  box-shadow: 0 0 0 3px var(--bg), 0 0 0 4px var(--gold), 0 0 22px 6px rgba(var(--gold-rgb), .55); }
.you .halo { position: absolute; left: -24px; top: -24px; width: 48px; height: 48px; border-radius: 50%;
  border: 1.5px solid var(--gold); opacity: 0; animation: halo 2.8s ease-out infinite; }
.radar { --r: 280px; position: absolute; width: var(--r); height: var(--r); left: calc(var(--r) / -2); top: calc(var(--r) / -2);
  border-radius: 50%; overflow: hidden; opacity: 0; transform: scale(.55); transition: opacity 450ms ease, transform 600ms cubic-bezier(.2,.8,.2,1); }
.radar.on { opacity: 1; transform: scale(1); }
.radar .disc { position: absolute; inset: 0; border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--gold-rgb), .16) 0%, rgba(var(--gold-rgb), .06) 55%, rgba(var(--gold-rgb), .02) 70%); }
.radar .ring { position: absolute; border-radius: 50%; border: 1px solid rgba(var(--gold-rgb), .28); }
.radar .r1 { inset: 33%; }
.radar .r2 { inset: 16.5%; }
.radar .r3 { inset: 1px; border-color: rgba(var(--gold-rgb), .5); }
.radar .cross { position: absolute; background: rgba(var(--gold-rgb), .14); }
.radar .cross.h { left: 0; right: 0; top: 50%; height: 1px; }
.radar .cross.v { top: 0; bottom: 0; left: 50%; width: 1px; }
.radar .sweep { position: absolute; inset: 0; border-radius: 50%;
  background: conic-gradient(from 0deg, rgba(var(--gold-rgb), 0) 0deg, rgba(var(--gold-rgb), 0) 250deg, rgba(var(--gold-rgb), .1) 300deg, rgba(var(--gold-rgb), .5) 359deg, rgba(var(--gold-rgb), 0) 360deg); }
.radar .sweep::after { content: ''; position: absolute; left: 50%; top: 0; width: 2px; height: 50%; margin-left: -1px;
  background: linear-gradient(to top, rgba(var(--gold-rgb), .1), var(--gold)); box-shadow: 0 0 8px rgba(var(--gold-rgb), .9); }
.radar.on .sweep { animation: spin var(--sweep) linear infinite; }
.pin-root { width: 42px; height: 42px; }
.pin { position: relative; display: block; width: 42px; height: 42px; padding: 0; border: 0; background: none; cursor: pointer;
  opacity: 0; transform: scale(.3); transition: opacity 220ms ease, transform 560ms cubic-bezier(.18,1.55,.4,1); }
.pin.found { opacity: 1; transform: scale(1); }
.pin .face { position: absolute; inset: 0; border-radius: 50%; overflow: hidden; border: 2px solid var(--gold);
  box-shadow: 0 8px 18px rgba(0,0,0,.5); background: var(--gold); color: var(--on-gold);
  display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; }
.pin .face img { width: 100%; height: 100%; object-fit: cover; display: block; }
.pin .name { position: absolute; top: 46px; left: 50%; transform: translateX(-50%); max-width: 128px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; padding: 2px 9px; border-radius: 999px; background: var(--scrim);
  color: var(--text); font-size: 11px; font-weight: 600; letter-spacing: .2px; }
.pin.found::before { content: ''; position: absolute; inset: -7px; border-radius: 50%; border: 2px solid var(--gold);
  opacity: 0; animation: ping 1s ease-out 1; }
.pin:active .face { transform: scale(.94); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes halo { 0% { transform: scale(.4); opacity: .9; } 100% { transform: scale(1.7); opacity: 0; } }
@keyframes ping { 0% { transform: scale(.7); opacity: .9; } 100% { transform: scale(1.9); opacity: 0; } }
.reduce .radar .sweep, .reduce .you .halo, .reduce .pin.found::before { animation: none; display: none; }
.reduce .pin, .reduce .radar { transition: opacity 150ms linear; transform: none; }
</style>
</head>
<body>
<div id="map"></div>
<script src="${MAPLIBRE_SCRIPT.url}" integrity="${MAPLIBRE_SCRIPT.integrity}" crossorigin="anonymous"></script>
<script>
(function () {
  'use strict';
  var CONFIG = ${scriptJson(config)};
  function post(message) {
    try { window.ReactNativeWebView.postMessage(JSON.stringify(message)); } catch (e) {}
  }
  if (CONFIG.reduceMotion) document.documentElement.classList.add('reduce');
  if (!window.maplibregl) { post({ type: 'error', reason: 'script' }); return; }
  var map;
  try {
    map = new maplibregl.Map({
      container: 'map', style: CONFIG.styleUrl, center: [10, 30], zoom: 1.3, minZoom: 1, maxZoom: 15.5,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false, touchPitch: false, maxPitch: 0
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disable();
    map.setPadding({ top: CONFIG.topInset, bottom: 0, left: 0, right: 0 });
  } catch (e) { post({ type: 'error', reason: 'webgl' }); return; }

  var loaded = false;
  var timer = setTimeout(function () { if (!loaded) post({ type: 'error', reason: 'timeout' }); }, CONFIG.loadTimeoutMs);
  map.on('load', function () {
    loaded = true;
    clearTimeout(timer);
    try { if (map.getLayer('background')) map.setPaintProperty('background', 'background-color', CONFIG.background); } catch (e) {}
    post({ type: 'loaded' });
  });

  var you = null, radius = 2000, youMarker = null, radar = null, scanning = false, sweepStart = 0, markers = [];

  function el(tag, cls) { var node = document.createElement(tag); if (cls) node.className = cls; return node; }
  function radarPx() { var c = map.getContainer(); return Math.round(Math.min(c.clientWidth, c.clientHeight) * 0.9); }
  function zoomFor(lat, metres) {
    // Metres per pixel at zoom z with 512 px tiles: 78271.52 * cos(lat) / 2^z.
    var px = radarPx() / 2 * 0.92;
    return Math.max(1, Math.min(14, Math.log2(78271.52 * Math.cos(lat * Math.PI / 180) * px / metres)));
  }
  function ensureYou() {
    if (youMarker) { youMarker.setLngLat([you.lng, you.lat]); return; }
    var root = el('div', 'you');
    radar = el('div', 'radar');
    ['disc', 'ring r1', 'ring r2', 'ring r3', 'cross h', 'cross v', 'sweep'].forEach(function (c) { radar.appendChild(el('div', c)); });
    root.appendChild(radar);
    root.appendChild(el('div', 'halo'));
    root.appendChild(el('div', 'dot'));
    youMarker = new maplibregl.Marker({ element: root, anchor: 'center' }).setLngLat([you.lng, you.lat]).addTo(map);
  }
  function clearPins() { markers.forEach(function (m) { m.remove(); }); markers = []; }
  function view(cmd) {
    you = { lat: Number(cmd.center.lat), lng: Number(cmd.center.lng) };
    radius = Math.max(200, Number(cmd.radiusM) || 2000);
    ensureYou();
    var target = { center: [you.lng, you.lat], zoom: zoomFor(you.lat, radius) };
    if (cmd.animate && !CONFIG.reduceMotion) { target.duration = 1400; target.essential = true; map.flyTo(target); }
    else map.jumpTo(target);
  }
  function scan() {
    if (!you) return;
    clearPins();
    scanning = true;
    radar.style.setProperty('--r', radarPx() + 'px');
    map.easeTo({ center: [you.lng, you.lat], zoom: zoomFor(you.lat, radius), duration: CONFIG.reduceMotion ? 0 : 500 });
    collapseAttribution();
    radar.classList.remove('on');
    void radar.offsetWidth;
    radar.classList.add('on');
    sweepStart = performance.now();
  }
  // The credit stays one tap away on the (i) button while results are shown.
  function collapseAttribution() {
    var attribution = document.querySelector('.maplibregl-ctrl-attrib');
    if (attribution) attribution.classList.remove('maplibregl-compact-show');
  }
  function stop() { scanning = false; if (radar) radar.classList.remove('on'); }
  function bearing(lng, lat) {
    var c = map.project([you.lng, you.lat]), p = map.project([lng, lat]);
    return (Math.atan2(p.x - c.x, c.y - p.y) * 180 / Math.PI + 360) % 360;
  }
  function addPin(pin) {
    var root = el('div', 'pin-root');
    var button = el('button', 'pin');
    button.type = 'button';
    button.setAttribute('aria-label', String(pin.label || pin.name || ''));
    var face = el('span', 'face');
    var initial = String(pin.initial || '?').slice(0, 2);
    if (typeof pin.avatarUrl === 'string' && pin.avatarUrl.indexOf('https://') === 0) {
      var img = el('img');
      img.alt = '';
      img.referrerPolicy = 'no-referrer';
      img.onerror = function () { img.remove(); face.textContent = initial; };
      img.src = pin.avatarUrl;
      face.appendChild(img);
    } else {
      face.textContent = initial;
    }
    var name = el('span', 'name');
    name.textContent = String(pin.name || '');
    button.appendChild(face);
    button.appendChild(name);
    button.addEventListener('click', function (event) { event.stopPropagation(); post({ type: 'open', id: String(pin.id) }); });
    root.appendChild(button);
    markers.push(new maplibregl.Marker({ element: root, anchor: 'center' }).setLngLat([Number(pin.lng), Number(pin.lat)]).addTo(map));
    return button;
  }
  // Pins normally fit the radar's view. If the traveller moved the map away, bring them back.
  function fit(pins) {
    if (!pins.length || !you) return;
    var visible = map.getBounds();
    var inside = pins.every(function (p) { return visible.contains([p.lng, p.lat]); });
    if (inside) return;
    var bounds = new maplibregl.LngLatBounds([you.lng, you.lat], [you.lng, you.lat]);
    pins.forEach(function (p) { bounds.extend([p.lng, p.lat]); });
    map.fitBounds(bounds, {
      padding: { top: 80, bottom: 48, left: 40, right: 40 },
      maxZoom: 14,
      duration: CONFIG.reduceMotion ? 0 : 800
    });
  }
  function showPins(pins) {
    clearPins();
    var buttons = pins.map(addPin);
    if (!scanning || !you) {
      buttons.forEach(function (b) { b.classList.add('found'); });
      fit(pins);
      return;
    }
    var period = CONFIG.sweepMs;
    var angle = CONFIG.reduceMotion ? 0 : ((performance.now() - sweepStart) / period * 360) % 360;
    pins.forEach(function (p, i) {
      var delay = CONFIG.reduceMotion ? i * 60 : ((bearing(p.lng, p.lat) - angle + 360) % 360) / 360 * period;
      setTimeout(function () { buttons[i].classList.add('found'); }, delay);
    });
    setTimeout(function () { stop(); fit(pins); post({ type: 'revealed' }); },
      CONFIG.reduceMotion ? pins.length * 60 + 150 : period + 200);
  }
  function apply(cmd) {
    if (!cmd || typeof cmd.type !== 'string') return;
    if (cmd.type === 'view' && cmd.center) view(cmd);
    else if (cmd.type === 'scan') scan();
    else if (cmd.type === 'pins') showPins(Array.isArray(cmd.pins) ? cmd.pins : []);
    else if (cmd.type === 'stop') stop();
    else if (cmd.type === 'clear') { stop(); clearPins(); }
  }
  window.tbMap = { apply: apply };
  post({ type: 'ready' });
})();
</script>
</body>
</html>`;
}

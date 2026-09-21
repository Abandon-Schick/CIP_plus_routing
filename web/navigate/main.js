import { boundsOfGeometry, buildRouteIndex, lerpAngleDeg } from "./geo.js";
import { GpsSource } from "./gps.js";
import { RouteSimulator } from "./simulator.js";
import { ActiveCardTracker } from "./tracker.js";

const params = new URLSearchParams(location.search);
// Demo default: 700 East Main Street -> 1200 Semmes Avenue, Richmond (walking).
const DEFAULT_START = "-77.4376041,37.5393687";
const DEFAULT_END = "-77.4488098,37.5246138";
const BASEMAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const FOLLOW_ZOOM = 17;
const METERS_PER_MILE = 1609.344;
const BASE_SPEED_MPS = { walking: 1.4, biking: 4.5, driving: 11 };
// A real GPS jitters at corridor edges; keep a card up for this many samples after leaving it.
const GPS_HOLD_SAMPLES = 2;
const ARRIVED_WITHIN_M = 25;
// Simulator speed multipliers offered in the panel, and how long a run may take by default.
const SIM_SPEEDS = [1, 5, 15, 40, 100];
const SIM_DEFAULT_MAX_SECONDS = 360;

const GPS_MESSAGES = {
  searching: ["Finding your location…", false],
  weak: ["Weak GPS signal — waiting for a better fix…", true],
  denied: ["Location is blocked. Allow it in your browser's site settings, or use Simulate.", true],
  unavailable: ["Can't get a location right now.", true],
  unsupported: ["This browser can't share its location.", true],
  insecure: ["Location needs a secure (https) connection.", true],
};

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function showStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  statusEl.hidden = false;
}

function parseLonLat(text) {
  const [lon, lat] = text.split(",").map(Number);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) throw new Error(`Bad coordinate: ${text}`);
  return { lon, lat };
}

async function loadPlan() {
  const mode = params.get("mode") || "walking";
  // A bundled GPX route is named by id; anything else is routed from start to end.
  const routeId = params.get("route");
  const body = routeId
    ? { route_id: routeId, mode }
    : {
        start: parseLonLat(params.get("start") || DEFAULT_START),
        end: parseLonLat(params.get("end") || DEFAULT_END),
        mode,
      };
  const response = await fetch("/navigation-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch {}
    throw new Error(`Couldn't load the route (${detail}).`);
  }
  return { plan: await response.json(), mode };
}

function routeCoordinates(geometry) {
  return geometry.type === "MultiLineString" ? geometry.coordinates.flat() : geometry.coordinates;
}

function renderCards(container, cards, colorOf, quietTitle) {
  container.replaceChildren();
  const list = cards.length
    ? cards
    : [{ bucket: "unaffected", title: quietTitle, detail: "", quiet: true }];
  for (const card of list) {
    const el = document.createElement("article");
    el.className = card.quiet ? "card quiet" : "card";
    el.style.setProperty("--c", colorOf(card.bucket));
    if (!card.quiet) {
      const bucket = document.createElement("div");
      bucket.className = "bucket";
      bucket.textContent = card.bucketLabel;
      el.append(bucket);
    }
    const title = document.createElement("h2");
    title.textContent = card.title;
    el.append(title);
    if (card.detail) {
      const detail = document.createElement("p");
      detail.textContent = card.detail;
      el.append(detail);
    }
    container.append(el);
  }
}

function addRouteLayers(map, plan, colorOf) {
  const corridorFeatures = plan.cards.map((card, i) => ({
    type: "Feature",
    id: i,
    geometry: card.corridor,
    properties: { color: colorOf(card.bucket) },
  }));
  map.addSource("corridors", { type: "geojson", data: { type: "FeatureCollection", features: corridorFeatures } });
  map.addLayer({
    id: "corridors-fill",
    type: "fill",
    source: "corridors",
    paint: {
      "fill-color": ["get", "color"],
      "fill-opacity": ["case", ["boolean", ["feature-state", "active"], false], 0.24, 0.08],
    },
  });
  map.addLayer({
    id: "corridors-line",
    type: "line",
    source: "corridors",
    paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.6 },
  });

  const segmentFeatures = plan.route.segments.map((segment) => ({
    type: "Feature",
    geometry: { type: "LineString", coordinates: segment.path },
    properties: { color: colorOf(segment.bucket) },
  }));
  map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: segmentFeatures } });
  const lineLayout = { "line-cap": "round", "line-join": "round" };
  map.addLayer({
    id: "route-casing",
    type: "line",
    source: "route",
    layout: lineLayout,
    paint: { "line-color": "#ffffff", "line-width": 10 },
  });
  map.addLayer({
    id: "route-line",
    type: "line",
    source: "route",
    layout: lineLayout,
    paint: { "line-color": ["get", "color"], "line-width": 6 },
  });

  const coords = routeCoordinates(plan.route.geometry);
  map.addSource("endpoints", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: coords[0] }, properties: { color: "#16a34a" } },
        { type: "Feature", geometry: { type: "Point", coordinates: coords[coords.length - 1] }, properties: { color: "#111827" } },
      ],
    },
  });
  map.addLayer({
    id: "endpoints",
    type: "circle",
    source: "endpoints",
    paint: {
      "circle-radius": 7,
      "circle-color": ["get", "color"],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 3,
    },
  });
}

async function main() {
  let loaded;
  try {
    loaded = await loadPlan();
  } catch (error) {
    showStatus(error.message, true);
    return;
  }
  const { plan, mode } = loaded;

  const buckets = Object.fromEntries(plan.buckets.map((b) => [b.key, b]));
  const colorOf = (key) => (buckets[key] || buckets.unaffected).color;
  const labelOf = (key) => (buckets[key] || buckets.unaffected).label;
  for (const card of plan.cards) {
    card.bounds = boundsOfGeometry(card.corridor);
    card.bucketLabel = labelOf(card.bucket);
  }

  const coords = routeCoordinates(plan.route.geometry);
  const route = buildRouteIndex(coords);
  const baseSpeedMps = BASE_SPEED_MPS[mode] ?? BASE_SPEED_MPS.walking;
  const simulator = new RouteSimulator(route, baseSpeedMps);
  // Default to 5x, or the slowest speed that keeps a long route (e.g. a GPX ride) watchable.
  $("sim-speed").value = String(
    SIM_SPEEDS.find((x) => x >= 5 && route.totalM / (baseSpeedMps * x) <= SIM_DEFAULT_MAX_SECONDS) ??
      SIM_SPEEDS[SIM_SPEEDS.length - 1],
  );

  const map = new maplibregl.Map({
    container: "map",
    style: BASEMAP_STYLE,
    center: coords[0],
    zoom: FOLLOW_ZOOM,
    pitch: 0,
    dragRotate: false,
    attributionControl: { compact: true },
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();

  await new Promise((resolve) => map.once("load", resolve));
  addRouteLayers(map, plan, colorOf);

  const meEl = document.createElement("div");
  meEl.className = "me";
  const me = new maplibregl.Marker({ element: meEl, rotationAlignment: "map", pitchAlignment: "map" })
    .setLngLat(coords[0])
    .addTo(map);

  const infoBar = $("info-bar");
  const cardsEl = $("cards");
  const remainingEl = $("remaining");
  const recenterBtn = $("recenter");
  const gpsStatusEl = $("gps-status");

  let source = null;
  let gps = null;
  let activeTracker = new ActiveCardTracker(plan.cards, 0);
  let following = true;
  let followZoom = FOLLOW_ZOOM;
  let displayBearing = null;
  let lastFrameTime = null;
  let lastFrameFix = null;
  let activeKey = null;
  let activeIds = new Set();

  function cameraPadding() {
    const bottom = infoBar.getBoundingClientRect().height;
    const visible = window.innerHeight - bottom;
    return { top: Math.max(0, visible * 0.36), bottom, left: 0, right: 0 };
  }

  function setActiveCorridors(nextIds) {
    plan.cards.forEach((card, i) => {
      const was = activeIds.has(card.id);
      const now = nextIds.has(card.id);
      if (was !== now) map.setFeatureState({ source: "corridors", id: i }, { active: now });
    });
    activeIds = nextIds;
  }

  function showCards(active, quietTitle = labelOf("unaffected")) {
    const key = active.map((c) => c.id).join("|");
    if (key === activeKey) return;
    activeKey = key;
    setActiveCorridors(new Set(active.map((c) => c.id)));
    renderCards(cardsEl, active, colorOf, quietTitle);
    cardsEl.scrollTop = 0;
  }

  // Once per position sample: which cards apply, and how far is left.
  function onSample(fix) {
    showCards(activeTracker.update([fix.lon, fix.lat]));
    meEl.classList.toggle("off-route", fix.onRoute === false);
    const leftM = Math.max(0, route.totalM - fix.distanceAlongM);
    if (fix.onRoute === false) remainingEl.textContent = "Off route";
    else remainingEl.textContent = leftM < ARRIVED_WITHIN_M ? "Arrived" : `${(leftM / METERS_PER_MILE).toFixed(2)} mi to go`;
    if (source === "sim") $("sim-progress").value = String(Math.round((fix.distanceAlongM / route.totalM) * 1000));
  }

  // Every animation frame: marker and camera.
  function onFrame(fix) {
    lastFrameFix = fix;
    const now = performance.now();
    const dt = lastFrameTime === null ? Infinity : (now - lastFrameTime) / 1000;
    lastFrameTime = now;
    displayBearing =
      displayBearing === null || !Number.isFinite(dt)
        ? fix.heading
        : lerpAngleDeg(displayBearing, fix.heading, 1 - Math.exp(-dt / 0.35));

    meEl.style.display = "";
    me.setLngLat([fix.lon, fix.lat]).setRotation(fix.heading);
    if (following) {
      map.jumpTo({ center: [fix.lon, fix.lat], bearing: displayBearing, zoom: followZoom, padding: cameraPadding() });
    }
  }

  function showGpsStatus({ state, accuracyM }) {
    if (state === "tracking") {
      gpsStatusEl.textContent = `GPS ±${Math.round(accuracyM)} m`;
      gpsStatusEl.classList.remove("problem");
    } else {
      const [message, isProblem] = GPS_MESSAGES[state];
      gpsStatusEl.textContent = state === "weak" ? `Weak GPS signal (±${Math.round(accuracyM)} m) — waiting…` : message;
      gpsStatusEl.classList.toggle("problem", isProblem);
    }
    gpsStatusEl.hidden = false;
  }

  function setSource(name) {
    simulator.pause();
    gps?.stop();
    gps = null;
    source = name;

    $("source-sim").setAttribute("aria-pressed", String(name === "sim"));
    $("source-gps").setAttribute("aria-pressed", String(name === "gps"));
    $("sim-controls").hidden = name !== "sim";
    gpsStatusEl.hidden = name !== "gps";

    activeTracker = new ActiveCardTracker(plan.cards, name === "gps" ? GPS_HOLD_SAMPLES : 0);
    activeKey = null;
    setActiveCorridors(new Set());
    displayBearing = null;
    lastFrameTime = null;
    following = true;
    recenterBtn.hidden = true;

    if (name === "sim") {
      simulator.emit();
      return;
    }
    meEl.style.display = "none";
    showCards([], "Waiting for your location…");
    remainingEl.textContent = "";
    gps = new GpsSource(route);
    gps.onFrame = onFrame;
    gps.onSample = onSample;
    gps.onStatus = showGpsStatus;
    gps.start();
  }

  map.on("dragstart", () => {
    following = false;
    recenterBtn.hidden = false;
  });
  map.on("zoomend", (event) => {
    if (event.originalEvent) followZoom = map.getZoom();
  });
  recenterBtn.addEventListener("click", () => {
    following = true;
    recenterBtn.hidden = true;
    if (lastFrameFix) onFrame(lastFrameFix);
  });
  new ResizeObserver(() => {
    if (following) map.jumpTo({ padding: cameraPadding() });
  }).observe(infoBar);

  // Simulated location controls.
  const playBtn = $("sim-play");
  simulator.onFrame = onFrame;
  simulator.onSample = onSample;
  simulator.multiplier = Number($("sim-speed").value);
  simulator.onPlayingChange = (playing) => {
    playBtn.textContent = playing ? "❚❚" : "▶";
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  };
  playBtn.addEventListener("click", () => (simulator.playing ? simulator.pause() : simulator.play()));
  $("sim-speed").addEventListener("change", (event) => {
    simulator.multiplier = Number(event.target.value);
  });
  $("sim-progress").addEventListener("input", (event) => {
    simulator.seekFraction(Number(event.target.value) / 1000);
  });
  $("source-sim").addEventListener("click", () => source !== "sim" && setSource("sim"));
  $("source-gps").addEventListener("click", () => source !== "gps" && setSource("gps"));

  statusEl.hidden = true;
  // A link meant for a phone (?source=gps) opens on a route overview and waits for a tap:
  // the location prompt and screen wake lock both work best from a user gesture.
  if (params.get("source") === "gps") {
    const bounds = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]));
    map.fitBounds(bounds, { padding: { top: 60, left: 40, right: 40, bottom: 340 }, animate: false });
    meEl.style.display = "none";
    infoBar.hidden = true;
    $("start-overlay").hidden = false;
    const begin = (name) => {
      $("start-overlay").hidden = true;
      infoBar.hidden = false;
      $("location-panel").hidden = false;
      setSource(name);
    };
    $("start-gps").addEventListener("click", () => begin("gps"));
    $("start-sim").addEventListener("click", () => begin("sim"));
  } else {
    infoBar.hidden = false;
    $("location-panel").hidden = false;
    setSource("sim");
    // An explicit ?source=sim (the Simulate button) starts walking straight away.
    if (params.get("source") === "sim") simulator.play();
  }

  if (params.has("debug")) window.__nav = { map, simulator, plan, route, setSource, getGps: () => gps };
}

main().catch((error) => showStatus(`Something went wrong: ${error.message}`, true));

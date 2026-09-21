import {
  activeCards,
  boundsOfGeometry,
  buildRouteIndex,
  lerpAngleDeg,
} from "./geo.js";
import { RouteSimulator } from "./simulator.js";

const params = new URLSearchParams(location.search);
// Demo default: 700 East Main Street -> 1200 Semmes Avenue, Richmond (walking).
const DEFAULT_START = "-77.4376041,37.5393687";
const DEFAULT_END = "-77.4488098,37.5246138";
const BASEMAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const FOLLOW_ZOOM = 17;
const METERS_PER_MILE = 1609.344;
const BASE_SPEED_MPS = { walking: 1.4, biking: 4.5, driving: 11 };

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
  const body = {
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

function renderCards(container, cards, colorOf, labelOf) {
  container.replaceChildren();
  const list = cards.length
    ? cards
    : [{ bucket: "unaffected", title: labelOf("unaffected"), detail: "", quiet: true }];
  for (const card of list) {
    const el = document.createElement("article");
    el.className = card.quiet ? "card quiet" : "card";
    el.style.setProperty("--c", colorOf(card.bucket));
    if (!card.quiet) {
      const bucket = document.createElement("div");
      bucket.className = "bucket";
      bucket.textContent = labelOf(card.bucket);
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
  for (const card of plan.cards) card.bounds = boundsOfGeometry(card.corridor);

  const route = buildRouteIndex(routeCoordinates(plan.route.geometry));
  const simulator = new RouteSimulator(route, BASE_SPEED_MPS[mode] ?? BASE_SPEED_MPS.walking);

  const map = new maplibregl.Map({
    container: "map",
    style: BASEMAP_STYLE,
    center: routeCoordinates(plan.route.geometry)[0],
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
    .setLngLat(routeCoordinates(plan.route.geometry)[0])
    .addTo(map);

  const infoBar = $("info-bar");
  const cardsEl = $("cards");
  const remainingEl = $("remaining");
  const recenterBtn = $("recenter");

  let following = true;
  let followZoom = FOLLOW_ZOOM;
  let displayBearing = null;
  let lastFixTime = null;
  let activeKey = null;
  let activeIds = new Set();

  function cameraPadding() {
    const bar = infoBar.getBoundingClientRect();
    const bottom = bar.height;
    const visible = window.innerHeight - bottom;
    return { top: Math.max(0, visible * 0.36), bottom, left: 0, right: 0 };
  }

  function updateActiveCards(point) {
    const active = activeCards(point, plan.cards);
    const key = active.map((c) => c.id).join("|");
    if (key === activeKey) return;
    activeKey = key;
    const nextIds = new Set(active.map((c) => c.id));
    plan.cards.forEach((card, i) => {
      const was = activeIds.has(card.id);
      const now = nextIds.has(card.id);
      if (was !== now) map.setFeatureState({ source: "corridors", id: i }, { active: now });
    });
    activeIds = nextIds;
    renderCards(cardsEl, active, colorOf, labelOf);
    cardsEl.scrollTop = 0;
  }

  function handleFix(fix) {
    const point = [fix.lon, fix.lat];
    const now = performance.now();
    const dt = lastFixTime === null ? Infinity : (now - lastFixTime) / 1000;
    lastFixTime = now;
    displayBearing =
      displayBearing === null || !Number.isFinite(dt)
        ? fix.heading
        : lerpAngleDeg(displayBearing, fix.heading, 1 - Math.exp(-dt / 0.35));

    me.setLngLat(point).setRotation(fix.heading);
    if (following) {
      map.jumpTo({ center: point, bearing: displayBearing, zoom: followZoom, padding: cameraPadding() });
    }
    updateActiveCards(point);

    const leftMiles = Math.max(0, route.totalM - fix.distanceAlongM) / METERS_PER_MILE;
    remainingEl.textContent = leftMiles < 0.01 ? "Arrived" : `${leftMiles.toFixed(2)} mi to go`;
    $("sim-progress").value = String(Math.round((fix.distanceAlongM / route.totalM) * 1000));
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
    handleFix(simulator.fix());
  });
  new ResizeObserver(() => {
    if (following) map.jumpTo({ padding: cameraPadding() });
  }).observe(infoBar);

  // Simulated location controls.
  const playBtn = $("sim-play");
  simulator.onFix = handleFix;
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

  statusEl.hidden = true;
  infoBar.hidden = false;
  $("simulator").hidden = false;
  handleFix(simulator.fix());

  if (params.has("debug")) window.__nav = { map, simulator, plan, route };
}

main().catch((error) => showStatus(`Something went wrong: ${error.message}`, true));

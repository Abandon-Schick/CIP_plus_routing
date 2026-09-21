// Pure geometry helpers for navigation mode (no DOM, no map). Coordinates are [lon, lat].

const EARTH_RADIUS_M = 6371008.8;
const toRad = (deg) => (deg * Math.PI) / 180;
const toDeg = (rad) => (rad * 180) / Math.PI;

export function distanceM(a, b) {
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

// Initial compass bearing from a to b, degrees clockwise from north in [0, 360).
export function bearingDeg(a, b) {
  const dLon = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

// Move `current` toward `target` along the shortest arc; fraction in [0, 1].
export function lerpAngleDeg(current, target, fraction) {
  const delta = ((target - current + 540) % 360) - 180;
  return (current + delta * fraction + 360) % 360;
}

// A route as cumulative distances, so "position at N meters along" is a lookup.
export function buildRouteIndex(coords) {
  const cumulative = [0];
  for (let i = 1; i < coords.length; i++) {
    cumulative.push(cumulative[i - 1] + distanceM(coords[i - 1], coords[i]));
  }
  return { coords, cumulative, totalM: cumulative[cumulative.length - 1] };
}

export function pointAtDistance(index, meters) {
  const { coords, cumulative, totalM } = index;
  const m = Math.max(0, Math.min(meters, totalM));
  let lo = 0;
  let hi = cumulative.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cumulative[mid] <= m) lo = mid;
    else hi = mid;
  }
  const span = cumulative[hi] - cumulative[lo];
  const t = span > 0 ? (m - cumulative[lo]) / span : 0;
  return [
    coords[lo][0] + (coords[hi][0] - coords[lo][0]) * t,
    coords[lo][1] + (coords[hi][1] - coords[lo][1]) * t,
  ];
}

// Ray casting; ring is an array of [lon, lat]. Boundary points may go either way.
function inRing(point, ring) {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPolygon(point, rings) {
  if (!inRing(point, rings[0])) return false;
  for (let i = 1; i < rings.length; i++) {
    if (inRing(point, rings[i])) return false;
  }
  return true;
}

export function boundsOfGeometry(geometry) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  for (const rings of polygons) {
    for (const [x, y] of rings[0]) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
  return [minX, minY, maxX, maxY];
}

// Polygon / MultiPolygon containment with a cheap bounding-box reject first.
export function pointInGeometry(point, geometry, bounds = boundsOfGeometry(geometry)) {
  const [x, y] = point;
  if (x < bounds[0] || x > bounds[2] || y < bounds[1] || y > bounds[3]) return false;
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polygons.some((rings) => inPolygon(point, rings));
}

// Cards active at a position, in the order the server ranked them.
export function activeCards(point, cards) {
  return cards.filter((card) => pointInGeometry(point, card.corridor, card.bounds));
}

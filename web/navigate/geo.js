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

// Compass bearing of the route at `meters` along it, looking ahead a few meters (or back,
// at the very end) so it doesn't twitch on every vertex.
export function routeHeadingAt(index, meters, lookM = 12) {
  if (meters + lookM <= index.totalM) {
    return bearingDeg(pointAtDistance(index, meters), pointAtDistance(index, meters + lookM));
  }
  return bearingDeg(pointAtDistance(index, Math.max(meters - lookM, 0)), pointAtDistance(index, meters));
}

const METERS_PER_DEGREE_LAT = (EARTH_RADIUS_M * Math.PI) / 180;

// Closest point on the route to `point`, optionally only looking between two distances
// along it (so an out-and-back route can't snap to the wrong leg).
// When several stretches are about equally close (a route that retraces itself), prefer the
// earliest one within `preferEarlierWithinM` of the best: the caller is moving forward, so
// the pass it hasn't reached yet is the one it is on.
// Returns { distanceAlongM, offsetM, point } or null when the window holds no segment.
export function nearestOnRoute(index, point, { fromM = 0, toM = Infinity, preferEarlierWithinM = 0 } = {}) {
  const { coords, cumulative } = index;
  const metersPerDegreeLon = METERS_PER_DEGREE_LAT * Math.cos(toRad(point[1]));
  const local = (c) => [(c[0] - point[0]) * metersPerDegreeLon, (c[1] - point[1]) * METERS_PER_DEGREE_LAT];
  const candidates = [];
  for (let i = 0; i < coords.length - 1; i++) {
    const legM = cumulative[i + 1] - cumulative[i];
    if (cumulative[i + 1] < fromM || cumulative[i] > toM) continue;
    const a = local(coords[i]);
    const b = local(coords[i + 1]);
    const abx = b[0] - a[0];
    const aby = b[1] - a[1];
    const len2 = abx * abx + aby * aby;
    // Keep the result inside the window even when a leg straddles its edge.
    const tMin = legM > 0 ? Math.max(0, (fromM - cumulative[i]) / legM) : 0;
    const tMax = legM > 0 ? Math.min(1, (toM - cumulative[i]) / legM) : 1;
    const t = len2 > 0 ? Math.max(tMin, Math.min(tMax, -(a[0] * abx + a[1] * aby) / len2)) : 0;
    candidates.push({
      offsetM: Math.hypot(a[0] + abx * t, a[1] + aby * t),
      distanceAlongM: cumulative[i] + t * legM,
    });
  }
  if (candidates.length === 0) return null;
  const closest = candidates.reduce((a, c) => (c.offsetM < a.offsetM ? c : a));
  const chosen =
    preferEarlierWithinM > 0
      ? candidates
          .filter((c) => c.offsetM <= closest.offsetM + preferEarlierWithinM)
          .reduce((a, c) => (c.distanceAlongM < a.distanceAlongM ? c : a))
      : closest;
  chosen.point = pointAtDistance(index, chosen.distanceAlongM);
  return chosen;
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

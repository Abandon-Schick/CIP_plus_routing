// Turns raw, noisy location samples into what the map and info bar need: a display
// position (snapped onto the route when close to it), a heading, and distance along.
// Pure logic -- no DOM, no map, no clocks.
import { bearingDeg, distanceM, nearestOnRoute, pointInGeometry, routeHeadingAt } from "./geo.js";

export const TRACKER_DEFAULTS = {
  // Snap to the route when within this many meters (grows with a poor GPS accuracy, up to maxSnapM).
  snapM: 25,
  maxSnapM: 60,
  // Samples less accurate than this are ignored rather than trusted.
  maxAccuracyM: 100,
  // Movement needed before a new heading / travel direction is inferred (below this it's just noise).
  minMoveM: 8,
  // Where to look on the route relative to the last snapped spot, before falling back to the whole route:
  // ahead (allowing a little jitter backwards) and behind. Ahead wins unless behind is clearly closer,
  // so on a route that retraces itself the rider keeps moving forward instead of sliding back.
  backSlackM: 5,
  behindMarginM: 8,
  searchBackM: 100,
  searchAheadM: 300,
  // On a route that retraces itself, two passes look equally close; within this many meters of the
  // best match, take the earliest -- the one the rider hasn't passed yet.
  tieBreakM: 10,
};

const reverse = (bearing) => (bearing + 180) % 360;

export class LocationTracker {
  constructor(routeIndex, options = {}) {
    this.route = routeIndex;
    this.o = { ...TRACKER_DEFAULTS, ...options };
    this.lastAlongM = null;
    this.alongAnchorM = null;
    this.direction = 1; // +1 walking start -> end, -1 walking back toward the start
    this.rawAnchor = null;
    this.heading = null;
  }

  // raw: { lon, lat, accuracyM }.  Returns null for a sample to ignore, else
  // { lon, lat, heading, distanceAlongM, onRoute, offsetM, accuracyM }.
  update(raw) {
    const accuracyM = raw.accuracyM ?? 0;
    if (accuracyM > this.o.maxAccuracyM) return null;

    const point = [raw.lon, raw.lat];
    const snapThresholdM = Math.max(this.o.snapM, Math.min(accuracyM, this.o.maxSnapM));

    const search = (fromM, toM) =>
      nearestOnRoute(this.route, point, { fromM, toM, preferEarlierWithinM: this.o.tieBreakM });
    let hit = null;
    let jumped = false;
    if (this.lastAlongM !== null) {
      const ahead = search(this.lastAlongM - this.o.backSlackM, this.lastAlongM + this.o.searchAheadM);
      const behind = search(this.lastAlongM - this.o.searchBackM, this.lastAlongM - this.o.backSlackM);
      hit = ahead;
      if (behind !== null && (ahead === null || behind.offsetM + this.o.behindMarginM < ahead.offsetM)) {
        hit = behind;
      }
    }
    if (hit === null || hit.offsetM > snapThresholdM) {
      const global = search(0, Infinity);
      if (hit === null || global.offsetM < hit.offsetM) {
        hit = global;
        jumped = this.lastAlongM !== null;
      }
    }
    const onRoute = hit.offsetM <= snapThresholdM;

    if (onRoute) {
      if (this.alongAnchorM === null || jumped) this.alongAnchorM = hit.distanceAlongM;
      if (Math.abs(hit.distanceAlongM - this.alongAnchorM) >= this.o.minMoveM) {
        this.direction = hit.distanceAlongM > this.alongAnchorM ? 1 : -1;
        this.alongAnchorM = hit.distanceAlongM;
      }
      this.lastAlongM = hit.distanceAlongM;
      this.rawAnchor = point;
      const tangent = routeHeadingAt(this.route, hit.distanceAlongM);
      this.heading = this.direction > 0 ? tangent : reverse(tangent);
      return {
        lon: hit.point[0],
        lat: hit.point[1],
        heading: this.heading,
        distanceAlongM: hit.distanceAlongM,
        onRoute: true,
        offsetM: hit.offsetM,
        accuracyM,
      };
    }

    if (this.rawAnchor === null) {
      this.rawAnchor = point;
    } else if (distanceM(this.rawAnchor, point) >= this.o.minMoveM) {
      this.heading = bearingDeg(this.rawAnchor, point);
      this.rawAnchor = point;
    }
    if (this.heading === null) this.heading = routeHeadingAt(this.route, hit.distanceAlongM);
    return {
      lon: point[0],
      lat: point[1],
      heading: this.heading,
      distanceAlongM: this.lastAlongM ?? hit.distanceAlongM,
      onRoute: false,
      offsetM: hit.offsetM,
      accuracyM,
    };
  }
}

// Which cards apply at a position. A card that was active stays for `holdSamples` samples
// after the position leaves its corridor, so GPS jitter at a boundary doesn't flicker it.
export class ActiveCardTracker {
  constructor(cards, holdSamples = 0) {
    this.cards = cards;
    this.holdSamples = holdSamples;
    this.misses = new Map();
  }

  reset() {
    this.misses.clear();
  }

  // Active cards, in the server's ranking order.
  update(point) {
    const active = [];
    for (const card of this.cards) {
      if (pointInGeometry(point, card.corridor, card.bounds)) {
        this.misses.set(card.id, 0);
        active.push(card);
      } else if (this.misses.has(card.id)) {
        const misses = this.misses.get(card.id) + 1;
        if (misses <= this.holdSamples) {
          this.misses.set(card.id, misses);
          active.push(card);
        } else {
          this.misses.delete(card.id);
        }
      }
    }
    return active;
  }
}

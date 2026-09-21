// Dependency-free tests for the pure modules. Open /navigate/tests.html; the page title
// and #summary say PASS or FAIL, and window.__testResults holds the details.
import {
  boundsOfGeometry,
  bearingDeg,
  buildRouteIndex,
  distanceM,
  lerpAngleDeg,
  nearestOnRoute,
  pointAtDistance,
  pointInGeometry,
  routeHeadingAt,
} from "./geo.js";
import { ActiveCardTracker, LocationTracker } from "./tracker.js";

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const near = (a, b, tol) => Math.abs(a - b) <= tol;
const angleNear = (a, b, tol) => Math.abs(((a - b + 540) % 360) - 180) <= tol;

// A route running due north from Richmond, in 100 m steps (so it has real vertices).
const LAT0 = 37.54;
const LON0 = -77.44;
const M_PER_DEG_LAT = 111194.9;
const M_PER_DEG_LON = M_PER_DEG_LAT * Math.cos((LAT0 * Math.PI) / 180);
const northOf = (meters) => LAT0 + meters / M_PER_DEG_LAT;
const eastOf = (meters) => LON0 + meters / M_PER_DEG_LON;
const straight = buildRouteIndex([0, 100, 200, 300, 400, 500].map((m) => [LON0, northOf(m)]));
const at = (alongM, eastM = 0) => ({ lon: eastOf(eastM), lat: northOf(alongM) });

// ---- geo.js ----------------------------------------------------------------------------
check("distance: 0.001 deg lat ~ 111 m", near(distanceM([0, 0], [0, 0.001]), 111.19, 0.5));
check("bearing north", near(bearingDeg([0, 0], [0, 1]), 0, 1e-6));
check("bearing east", near(bearingDeg([0, 0], [1, 0]), 90, 1e-6));
check("bearing south", near(bearingDeg([0, 1], [0, 0]), 180, 1e-6));
check("bearing west", near(bearingDeg([1, 0], [0, 0]), 270, 1e-6));
check("lerpAngle wraps 350 -> 10 through north", angleNear(lerpAngleDeg(350, 10, 0.5), 0, 1e-6));
check("lerpAngle wraps 10 -> 350 through north", angleNear(lerpAngleDeg(10, 350, 0.5), 0, 1e-6));
check("lerpAngle fraction 1 reaches target", near(lerpAngleDeg(100, 200, 1), 200, 1e-6));

check("route total ~ 500 m", near(straight.totalM, 500, 1));
check("pointAtDistance midpoint", near(pointAtDistance(straight, 250)[1], northOf(250), 1e-7));
check("pointAtDistance clamps below", pointAtDistance(straight, -5)[1] === northOf(0));
check("pointAtDistance clamps above", near(pointAtDistance(straight, 1e9)[1], northOf(500), 1e-7));
check(
  "zero-length leg does not break pointAtDistance",
  Number.isFinite(pointAtDistance(buildRouteIndex([[0, 0], [0, 0], [0, 0.001]]), 10)[1]),
);
check("routeHeadingAt northbound", angleNear(routeHeadingAt(straight, 100), 0, 0.5));
check("routeHeadingAt at the very end still northbound", angleNear(routeHeadingAt(straight, 500), 0, 0.5));

const square = { type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] };
const donut = { type: "Polygon", coordinates: [square.coordinates[0], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]] };
const multi = { type: "MultiPolygon", coordinates: [square.coordinates, [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]] };
check("point inside polygon", pointInGeometry([5, 5], square));
check("point outside polygon", !pointInGeometry([11, 5], square));
check("hole excluded", !pointInGeometry([5, 5], donut));
check("ring around hole included", pointInGeometry([2, 2], donut));
check("multipolygon second part", pointInGeometry([25, 25], multi));
check("multipolygon gap", !pointInGeometry([15, 15], multi));
check("bounds of multipolygon", boundsOfGeometry(multi).join() === "0,0,30,30");

const p10 = nearestOnRoute(straight, [eastOf(10), northOf(250)]);
check("nearestOnRoute: offset ~10 m", near(p10.offsetM, 10, 0.2), p10.offsetM);
check("nearestOnRoute: along ~250 m", near(p10.distanceAlongM, 250, 0.5), p10.distanceAlongM);
check("nearestOnRoute: snapped point on the route", near(p10.point[0], LON0, 1e-9));
const beforeStart = nearestOnRoute(straight, [LON0, northOf(-50)]);
check("nearestOnRoute clamps to the start", near(beforeStart.distanceAlongM, 0, 1e-6) && near(beforeStart.offsetM, 50, 0.5));
check("nearestOnRoute: empty window -> null", nearestOnRoute(straight, [LON0, LAT0], { fromM: 900, toM: 1000 }) === null);

// An out-and-back route: north along lon0, then back south 15 m to the east.
const outBack = buildRouteIndex([
  [LON0, northOf(0)], [LON0, northOf(500)], [eastOf(15), northOf(500)], [eastOf(15), northOf(0)],
]);
const nearReturnLeg = [eastOf(14), northOf(300)];
const anywhere = nearestOnRoute(outBack, nearReturnLeg);
const outboundOnly = nearestOnRoute(outBack, nearReturnLeg, { fromM: 0, toM: 500 });
check("out-and-back: unrestricted search finds the return leg", anywhere.distanceAlongM > 500, anywhere.distanceAlongM);
check("out-and-back: windowed search stays on the outbound leg", outboundOnly.distanceAlongM < 500, outboundOnly.distanceAlongM);

// ---- tracker.js: LocationTracker -------------------------------------------------------
{
  const tracker = new LocationTracker(straight);
  const fix = tracker.update({ ...at(200, 6), accuracyM: 8 });
  check("tracker: 6 m off snaps onto the route", fix.onRoute && near(fix.lon, LON0, 1e-9), JSON.stringify(fix));
  check("tracker: snapped along ~200 m", near(fix.distanceAlongM, 200, 0.5));
  check("tracker: snapped heading follows the route (north)", angleNear(fix.heading, 0, 0.5));
}
{
  const tracker = new LocationTracker(straight);
  const fix = tracker.update({ ...at(200, 40), accuracyM: 5 });
  check("tracker: 40 m off with good accuracy is off route", fix.onRoute === false);
  check("tracker: off-route keeps the raw position", near(fix.lon, eastOf(40), 1e-9));
  check("tracker: off-route with no movement yet borrows the route heading", angleNear(fix.heading, 0, 0.5));
}
{
  const tracker = new LocationTracker(straight);
  const fix = tracker.update({ ...at(200, 45), accuracyM: 50 });
  check("tracker: poor accuracy widens the snap distance", fix.onRoute === true);
}
check("tracker: very inaccurate sample is ignored", new LocationTracker(straight).update({ ...at(200), accuracyM: 150 }) === null);
{
  const tracker = new LocationTracker(straight);
  tracker.update({ ...at(300), accuracyM: 5 });
  tracker.update({ ...at(290), accuracyM: 5 });
  const fix = tracker.update({ ...at(275), accuracyM: 5 });
  check("tracker: walking back toward the start flips the heading south", angleNear(fix.heading, 180, 0.5), fix.heading);
  const resumed = new LocationTracker(straight);
  resumed.update({ ...at(100), accuracyM: 5 });
  const fwd = resumed.update({ ...at(115), accuracyM: 5 });
  check("tracker: walking forward keeps the heading north", angleNear(fwd.heading, 0, 0.5));
}
{
  const tracker = new LocationTracker(straight);
  tracker.update({ ...at(30, 40), accuracyM: 5 });
  const fix = tracker.update({ ...at(60, 40), accuracyM: 5 });
  check("tracker: off-route heading comes from movement, not the route", fix.onRoute === false && angleNear(fix.heading, 0, 0.5));
  const east = new LocationTracker(straight);
  east.update({ ...at(30, 40), accuracyM: 5 });
  const fixEast = east.update({ ...at(30, 70), accuracyM: 5 });
  check("tracker: heading follows a move to the east", angleNear(fixEast.heading, 90, 1), fixEast.heading);
  const jitter = new LocationTracker(straight);
  jitter.update({ ...at(30, 40), accuracyM: 5 });
  const held = jitter.update({ ...at(33, 41), accuracyM: 5 });
  check("tracker: sub-threshold jitter doesn't change the heading", angleNear(held.heading, 0, 0.5));
}
{
  const tracker = new LocationTracker(straight);
  tracker.update({ ...at(50), accuracyM: 5 });
  const away = tracker.update({ ...at(450, 5), accuracyM: 5 });
  check("tracker: a far-away sample re-acquires the route globally", away.onRoute && near(away.distanceAlongM, 450, 1), away.distanceAlongM);
}
{
  const tracker = new LocationTracker(outBack);
  tracker.update({ ...at(100, 2), accuracyM: 5 });
  const fix = tracker.update({ ...at(120, 1), accuracyM: 5 });
  check("tracker: out-and-back stays on the outbound leg near the start", fix.distanceAlongM < 500, fix.distanceAlongM);
}
{
  const tracker = new LocationTracker(straight);
  const leave = tracker.update({ ...at(300, 80), accuracyM: 5 });
  const back = tracker.update({ ...at(320, 3), accuracyM: 5 });
  check("tracker: leaving then rejoining the route", leave.onRoute === false && back.onRoute === true);
}

// A route that goes out 200 m and comes straight back along the same line: on the way back,
// samples must land on the return pass (along > 200), not the outbound one.
{
  const spur = buildRouteIndex([0, 100, 200, 100, 0].map((m) => [LON0, northOf(m)]));
  check("spur route is 400 m", near(spur.totalM, 400, 1));
  const tracker = new LocationTracker(spur);
  let worst = 0;
  let wentBackwards = 0;
  let previous = 0;
  for (let along = 0; along <= 400; along += 10) {
    const truthNorth = along <= 200 ? along : 400 - along;
    const fix = tracker.update({ lon: eastOf(((along * 7) % 9) - 4), lat: northOf(truthNorth), accuracyM: 8 });
    worst = Math.max(worst, Math.abs(fix.distanceAlongM - along));
    if (fix.distanceAlongM < previous - 20) wentBackwards++;
    previous = fix.distanceAlongM;
  }
  check("retrace: along stays within ~30 m of the truth on both passes", worst < 30, worst);
  check("retrace: never jumps backward onto the earlier pass", wentBackwards === 0, wentBackwards);
  const nearTip = nearestOnRoute(spur, [LON0, northOf(190)], { preferEarlierWithinM: 10 });
  check("retrace: nearestOnRoute prefers the earlier of two equally close passes", near(nearTip.distanceAlongM, 190, 1), nearTip.distanceAlongM);
  const plain = nearestOnRoute(spur, [LON0, northOf(190)]);
  check("retrace: without the preference either pass may win", plain.offsetM < 1);
}

// ---- tracker.js: ActiveCardTracker -----------------------------------------------------
{
  const cards = [{ id: "a", corridor: square }, { id: "b", corridor: multi }, { id: "c", corridor: donut }];
  cards.forEach((c) => (c.bounds = boundsOfGeometry(c.corridor)));
  const ids = (list) => list.map((c) => c.id).join();

  const instant = new ActiveCardTracker(cards, 0);
  check("cards: membership and server order", ids(instant.update([5, 5])) === "a,b");
  check("cards: none outside", ids(instant.update([50, 50])) === "");
  check("cards: hold 0 drops immediately", ids(instant.update([2, 2])) === "a,b,c" && ids(instant.update([15, 15])) === "");

  const held = new ActiveCardTracker(cards, 2);
  held.update([5, 5]);
  check("cards: hold keeps a card after 1 miss", ids(held.update([50, 50])) === "a,b");
  check("cards: hold keeps a card after 2 misses", ids(held.update([50, 50])) === "a,b");
  check("cards: hold drops on the 3rd miss", ids(held.update([50, 50])) === "");
  held.update([5, 5]);
  held.update([50, 50]);
  held.update([5, 5]);
  check("cards: re-entering resets the miss count", ids(held.update([50, 50])) === "a,b" && ids(held.update([50, 50])) === "a,b");
  check("cards: a card never seen doesn't linger", ids(new ActiveCardTracker(cards, 5).update([50, 50])) === "");
}

const failed = results.filter((r) => !r.ok);
window.__testResults = results;
document.getElementById("summary").textContent = failed.length
  ? `FAIL: ${failed.length} of ${results.length}`
  : `PASS: ${results.length} of ${results.length}`;
document.title = document.getElementById("summary").textContent;
document.getElementById("results").replaceChildren(
  ...results.map((r) => {
    const li = document.createElement("li");
    li.className = r.ok ? "pass" : "fail";
    li.textContent = `${r.ok ? "PASS" : "FAIL"} ${r.name}${r.ok || !r.detail ? "" : ` (${r.detail})`}`;
    return li;
  }),
);

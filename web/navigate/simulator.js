// Stand-in for a GPS: walks a fix along the route so the page can be developed and
// demoed on a laptop. Emits the same fix shape as the real source (gps.js):
// { lon, lat, heading, distanceAlongM, onRoute }.
import { pointAtDistance, routeHeadingAt } from "./geo.js";

export class RouteSimulator {
  constructor(routeIndex, baseSpeedMps) {
    this.route = routeIndex;
    this.baseSpeedMps = baseSpeedMps;
    this.multiplier = 1;
    this.distanceM = 0;
    this.playing = false;
    this.onFrame = () => {};
    this.onSample = () => {};
    this.onPlayingChange = () => {};
    this._lastFrame = 0;
    this._frame = null;
  }

  fix() {
    const here = pointAtDistance(this.route, this.distanceM);
    return {
      lon: here[0],
      lat: here[1],
      heading: routeHeadingAt(this.route, this.distanceM),
      distanceAlongM: this.distanceM,
      onRoute: true,
    };
  }

  emit() {
    const fix = this.fix();
    this.onSample(fix);
    this.onFrame(fix);
  }

  seekFraction(fraction) {
    this.distanceM = Math.max(0, Math.min(1, fraction)) * this.route.totalM;
    this.emit();
  }

  play() {
    if (this.playing) return;
    if (this.distanceM >= this.route.totalM) this.distanceM = 0;
    this.playing = true;
    this.onPlayingChange(true);
    this._lastFrame = performance.now();
    const step = (now) => {
      if (!this.playing) return;
      const dt = Math.min((now - this._lastFrame) / 1000, 0.25);
      this._lastFrame = now;
      this.distanceM = Math.min(this.distanceM + this.baseSpeedMps * this.multiplier * dt, this.route.totalM);
      this.emit();
      if (this.distanceM >= this.route.totalM) this.pause();
      else this._frame = requestAnimationFrame(step);
    };
    this._frame = requestAnimationFrame(step);
  }

  pause() {
    if (!this.playing) return;
    this.playing = false;
    cancelAnimationFrame(this._frame);
    this.onPlayingChange(false);
  }
}

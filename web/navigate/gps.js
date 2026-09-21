// Real location source. Emits the same fix shape as the simulator through two callbacks:
//   onSample(fix) -- once per real GPS sample (drives info-bar logic)
//   onFrame(fix)  -- every animation frame, gliding between samples (drives marker + camera)
// plus onStatus({ state, accuracyM }) for the UI.
import { LocationTracker } from "./tracker.js";
import { keepScreenOn } from "./wakelock.js";

const MIN_GLIDE_MS = 300;
const MAX_GLIDE_MS = 1500;
// A bigger jump than this (e.g. rejoining the route elsewhere) is shown instantly, not slid across the map.
const MAX_GLIDE_DISTANCE_DEG = 0.001;

const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
const lerp = (a, b, t) => a + (b - a) * t;

export class GpsSource {
  constructor(routeIndex, trackerOptions) {
    this.tracker = new LocationTracker(routeIndex, trackerOptions);
    this.onFrame = () => {};
    this.onSample = () => {};
    this.onStatus = () => {};
    this._watchId = null;
    this._releaseWakeLock = null;
    this._raf = null;
    this._current = null;
    this._from = null;
    this._to = null;
    this._glideStart = 0;
    this._glideMs = 1000;
    this._lastSampleAt = 0;
    this._step = this._step.bind(this);
  }

  start() {
    if (!window.isSecureContext) {
      this.onStatus({ state: "insecure" });
      return;
    }
    if (!("geolocation" in navigator)) {
      this.onStatus({ state: "unsupported" });
      return;
    }
    this.onStatus({ state: "searching" });
    this._releaseWakeLock = keepScreenOn();
    this._watchId = navigator.geolocation.watchPosition(
      (position) => this._handle(position),
      (error) => this._handleError(error),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 },
    );
  }

  stop() {
    if (this._watchId !== null) navigator.geolocation.clearWatch(this._watchId);
    this._watchId = null;
    cancelAnimationFrame(this._raf);
    this._raf = null;
    this._releaseWakeLock?.();
    this._releaseWakeLock = null;
  }

  _handle(position) {
    const { latitude, longitude, accuracy } = position.coords;
    const fix = this.tracker.update({ lon: longitude, lat: latitude, accuracyM: accuracy });
    if (fix === null) {
      this.onStatus({ state: "weak", accuracyM: accuracy });
      return;
    }
    this.onStatus({ state: "tracking", accuracyM: accuracy });
    this.onSample(fix);

    const now = performance.now();
    const isJump =
      this._current !== null &&
      Math.hypot(fix.lon - this._current.lon, fix.lat - this._current.lat) > MAX_GLIDE_DISTANCE_DEG;
    if (this._current === null || isJump) {
      this._current = fix;
      this._to = fix;
      this._lastSampleAt = now;
      this.onFrame(fix);
      return;
    }
    this._from = this._current;
    this._to = fix;
    this._glideStart = now;
    this._glideMs = clamp(now - this._lastSampleAt, MIN_GLIDE_MS, MAX_GLIDE_MS);
    this._lastSampleAt = now;
    if (this._raf === null) this._raf = requestAnimationFrame(this._step);
  }

  _step(now) {
    const t = clamp((now - this._glideStart) / this._glideMs, 0, 1);
    const from = this._from;
    const to = this._to;
    this._current = {
      ...to,
      lon: lerp(from.lon, to.lon, t),
      lat: lerp(from.lat, to.lat, t),
      distanceAlongM: lerp(from.distanceAlongM, to.distanceAlongM, t),
    };
    this.onFrame(this._current);
    this._raf = t < 1 ? requestAnimationFrame(this._step) : null;
  }

  _handleError(error) {
    // 1 = permission denied, 2 = position unavailable, 3 = timeout.
    const state = error.code === 1 ? "denied" : error.code === 3 ? "searching" : "unavailable";
    this.onStatus({ state });
    if (error.code === 1) this.stop();
  }
}

// Keeps the phone screen on while navigating: a web page stops receiving location
// updates once the screen sleeps. Returns a function that releases the lock.
export function keepScreenOn() {
  if (!("wakeLock" in navigator)) return () => {};
  let sentinel = null;
  let released = false;

  const acquire = async () => {
    try {
      sentinel = await navigator.wakeLock.request("screen");
    } catch {
      // Denied (e.g. low battery); navigation still works, the screen may just sleep.
    }
  };
  // The browser drops the lock whenever the page is hidden, so take it again on return.
  const onVisible = () => {
    if (!released && document.visibilityState === "visible") acquire();
  };
  document.addEventListener("visibilitychange", onVisible);
  acquire();

  return () => {
    released = true;
    document.removeEventListener("visibilitychange", onVisible);
    sentinel?.release().catch(() => {});
  };
}

import { useEffect } from "react";

/** The part of the Screen Wake Lock API used here (not in every TypeScript DOM lib). */
interface WakeLockSentinelLike {
  release(): Promise<void>;
}
interface WakeLockLike {
  request(type: "screen"): Promise<WakeLockSentinelLike>;
}

/**
 * Keeps the tablet screen awake while mounted (Screen Wake Lock, best effort). The browser drops
 * the lock whenever the page is hidden, so it is asked for again when the page becomes visible.
 * Unsupported browsers, a denied request or an insecure context are ignored: this never throws.
 */
export function useWakeLock(): void {
  useEffect(() => {
    const wakeLock = (navigator as Navigator & { wakeLock?: WakeLockLike }).wakeLock;
    if (!wakeLock) return;
    let lock: WakeLockSentinelLike | null = null;
    let active = true;

    const request = async () => {
      if (!active || document.visibilityState !== "visible") return;
      try {
        const next = await wakeLock.request("screen");
        if (active) lock = next;
        else void next.release().catch(() => {});
      } catch {
        // denied, low battery or not allowed here: the screen may sleep, nothing else breaks
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void request();
    };

    void request();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisible);
      if (lock) void lock.release().catch(() => {});
      lock = null;
    };
  }, []);
}

import { useEffect, useRef } from 'react';

/**
 * useVisibilityInterval
 *
 * Runs a periodic callback interval only when the document tab is visible.
 * When the document becomes hidden (background tab or minimized window),
 * the interval is paused to eliminate unnecessary idle network overhead and server load.
 * When the document becomes visible again, the callback is immediately triggered
 * to rehydrate fresh state and the interval resumes.
 *
 * @param callback The function to execute on each interval tick and on tab regain focus.
 * @param delayMs Interval delay in milliseconds.
 * @param enabled Optional flag to enable/disable the interval (defaults to true).
 */
export function useVisibilityInterval(
  callback: () => void,
  delayMs: number,
  enabled: boolean = true
): void {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled || delayMs <= 0) return;

    let timer: NodeJS.Timeout | null = null;

    const startTimer = () => {
      if (!timer) {
        timer = setInterval(() => {
          if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
            savedCallback.current();
          }
        }, delayMs);
      }
    };

    const stopTimer = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const handleVisibilityChange = () => {
      if (typeof document !== 'undefined') {
        if (document.visibilityState === 'visible') {
          savedCallback.current(); // Immediately refresh when tab regains focus
          startTimer();
        } else {
          stopTimer(); // Pause polling when tab is hidden
        }
      }
    };

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
      if (document.visibilityState === 'visible') {
        startTimer();
      }
    } else {
      startTimer();
    }

    return () => {
      stopTimer();
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
    };
  }, [delayMs, enabled]);
}

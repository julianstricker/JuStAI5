// Live camera view from an endless fragmented-MP4 stream (proxied go2rtc).
// A plain <video autoPlay> is not reliable for this: autoplay often does not start
// (the element sits on the first frame and looks like a snapshot), and a progressive
// stream drifts further behind real time. This player starts playback explicitly,
// stays near the live edge and aborts the download when it is removed.
import { useEffect, useRef, useState } from "react";

const MAX_LAG_S = 2.5;

export function LiveVideo({ src, rounded = 8 }: { src: string; rounded?: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"connecting" | "playing" | "error">("connecting");

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    setState("connecting");
    v.muted = true; // must be a property for autoplay policies, the React attribute is not enough
    v.defaultMuted = true;
    v.src = src;
    const play = () => {
      v.play().catch(() => undefined);
    };
    const keepLive = () => {
      if (!v.buffered.length) return;
      const end = v.buffered.end(v.buffered.length - 1);
      if (end - v.currentTime > MAX_LAG_S) v.currentTime = Math.max(0, end - 0.5);
    };
    const onPlaying = () => setState("playing");
    const onError = () => setState("error");
    v.addEventListener("loadeddata", play);
    v.addEventListener("canplay", play);
    v.addEventListener("playing", onPlaying);
    v.addEventListener("error", onError);
    // Browsers pause a growing stream when they reach the (provisional) end; nudge it on.
    const timer = window.setInterval(() => {
      keepLive();
      if (v.paused && v.readyState >= 2) play();
    }, 1000);
    return () => {
      window.clearInterval(timer);
      v.removeEventListener("loadeddata", play);
      v.removeEventListener("canplay", play);
      v.removeEventListener("playing", onPlaying);
      v.removeEventListener("error", onError);
      v.pause();
      v.removeAttribute("src"); // aborts the HTTP stream -> go2rtc can close the camera connection
      v.load();
    };
  }, [src]);

  return (
    <div style={{ position: "relative", width: "100%", background: "#000", borderRadius: rounded, minHeight: 120 }}>
      <video ref={ref} muted playsInline style={{ width: "100%", display: "block", borderRadius: rounded }} />
      {state !== "playing" && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#ddd",
            fontSize: 14,
          }}
        >
          {state === "error" ? "Livebild nicht verfügbar" : "Verbinde mit Kamera …"}
        </div>
      )}
    </div>
  );
}

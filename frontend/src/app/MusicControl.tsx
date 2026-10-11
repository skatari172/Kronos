import { useEffect } from "react";
import { Music, SkipForward, Volume2, VolumeX } from "lucide-react";
import { TRACKS, useMusic } from "./music";

/**
 * Soundtrack controls in the header: the track playing, next track, and mute.
 * Music starts on load where the browser allows it, otherwise on the first
 * click, key or touch (browsers block sound before one), unless it was muted
 * on an earlier visit.
 */
export function MusicControl() {
  const { muted, playing, track, toggleMute, next, wake } = useMusic();
  useEffect(() => {
    // Try at once: browsers that already trust this site play straight away.
    wake();
    // Otherwise the very first click, key or touch starts it (browsers block
    // sound until then); keep listening until sound is really running.
    const events = ["pointerdown", "keydown", "touchstart"] as const;
    const start = () => {
      wake();
      if (useMusic.getState().playing || useMusic.getState().muted)
        events.forEach((e) => window.removeEventListener(e, start, true));
    };
    events.forEach((e) => window.addEventListener(e, start, true));
    return () =>
      events.forEach((e) => window.removeEventListener(e, start, true));
  }, [wake]);
  return (
    <div className={`music-control ${playing && !muted ? "on" : ""}`}>
      <Music size={15} aria-hidden className="music-note" />
      <span className="music-title" title="Now playing">
        {muted ? "Music off" : TRACKS[track].name}
      </span>
      <button
        className="music-button"
        aria-label="Next track"
        title="Next track"
        onClick={next}
        disabled={muted}
      >
        <SkipForward size={15} />
      </button>
      <button
        className="music-button"
        aria-label={muted ? "Turn music on" : "Mute music"}
        aria-pressed={muted}
        title={muted ? "Turn music on" : "Mute"}
        onClick={toggleMute}
      >
        {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
      </button>
    </div>
  );
}

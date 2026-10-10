import { useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  Hourglass,
  Pause,
  Play,
  SkipForward,
} from "lucide-react";
import { useWorld } from "../stores/world";
import { growthOf, TIERS } from "../world/progress";
import { Village } from "../world/Village";
import { useSimulation } from "./useSimulation";

/** Full-screen village. Interface panels float over it as HUDs. */
export function App() {
  const update = useWorld((s) => s.update);
  const epoch = useWorld((s) => s.epoch);
  const sim = useSimulation();
  const [timelapse, setTimelapse] = useState(false);
  const growth = update ? growthOf(update.state, epoch) : null;
  const banner = useTierBanner(growth?.tier, epoch);

  if (!update || !growth)
    return (
      <main className="loading">
        <Hourglass size={36} />
        <h1>KRONOS</h1>
        <p>{sim.error || "A small world is taking shape…"}</p>
        {sim.error && (
          <button onClick={() => location.reload()}>Reconnect</button>
        )}
      </main>
    );

  const live = sim.mode === "live";
  const day = String(update.state.tick + 1).padStart(2, "0");
  const status = !live
    ? sim.preview || "Offline preview · press ⏭ to grow the village"
    : !sim.connected
      ? "Reconnecting"
      : timelapse
        ? "Time-lapse"
        : sim.playing
          ? "Life in motion"
          : "Paused";

  async function toggleTimelapse() {
    const next = !timelapse;
    setTimelapse(next);
    // Real simulation speed: 4× days, then back to normal.
    await sim.setPlayback(true, next ? 4 : 1);
  }

  return (
    <div className="stage">
      <Village autoRotate={timelapse} />
      <div className="growth" aria-label="Settlement growth">
        <span>OAKHAVEN</span>
        <strong>{growth.name}</strong>
        <div className="growth-bar">
          <i style={{ width: `${Math.round(growth.toNext * 100)}%` }} />
        </div>
        <small>{growth.next ? `Next: ${growth.next}` : "Fully grown"}</small>
      </div>
      {banner && (
        <div className="tier-banner" role="status" key={banner}>
          <small>OAKHAVEN IS NOW A</small>
          <strong>{banner}</strong>
        </div>
      )}
      <div className="hud" role="toolbar" aria-label="Simulation controls">
        <div className="hud-day">
          <strong>Day {day}</strong>
          <small>
            <i className={live && sim.connected ? "online" : ""} />
            {status}
          </small>
        </div>
        <span className="hud-divider" />
        <button
          className="hud-button primary"
          aria-label={sim.playing ? "Pause simulation" : "Play simulation"}
          disabled={!live || sim.busy}
          onClick={() => {
            setTimelapse(false);
            void sim.togglePlay();
          }}
        >
          {sim.playing ? <Pause size={17} /> : <Play size={17} />}
        </button>
        <button
          className="hud-button"
          aria-label={live ? "Advance one day" : "Next preview event"}
          disabled={sim.busy || (live && sim.playing)}
          onClick={() => void sim.step()}
        >
          <SkipForward size={17} />
        </button>
        <select
          aria-label="Simulation speed"
          value={sim.speed}
          disabled={!live || sim.busy}
          onChange={(e) => sim.changeSpeed(Number(e.target.value))}
        >
          <option value={1}>1×</option>
          <option value={2}>2×</option>
          <option value={4}>4×</option>
        </select>
        <button
          className={`hud-button ${timelapse ? "active" : ""}`}
          aria-label={timelapse ? "Stop time-lapse" : "Start time-lapse"}
          aria-pressed={timelapse}
          title="Time-lapse: 4× days with a slow orbit"
          disabled={!live || sim.busy}
          onClick={() => void toggleTimelapse()}
        >
          <Clapperboard size={17} />
        </button>
      </div>
      {sim.error && (
        <div className="hud-error" role="status">
          {sim.error}
        </div>
      )}
    </div>
  );
}

/**
 * Announce a new tier for a few seconds. Seeks and branch switches (a new
 * epoch) set the baseline silently instead of celebrating.
 */
function useTierBanner(tier: number | undefined, epoch: number) {
  const [banner, setBanner] = useState<string | null>(null);
  const seen = useRef<{ tier?: number; epoch: number }>({ epoch });
  useEffect(() => {
    if (tier === undefined) return;
    const previous = seen.current;
    seen.current = { tier, epoch };
    if (previous.tier === undefined || previous.epoch !== epoch) return;
    if (tier <= previous.tier) return;
    setBanner(TIERS[tier]);
    const timer = setTimeout(() => setBanner(null), 4200);
    return () => clearTimeout(timer);
  }, [tier, epoch]);
  return banner;
}

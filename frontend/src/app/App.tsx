import { useEffect, useRef, useState } from "react";
import { Clapperboard, Hourglass, Pause, Play } from "lucide-react";
import type { WorldState } from "../api/types";
import { usePlayback, useWorld } from "../stores/world";
import { growthOf, TIERS } from "../world/progress";
import { Village } from "../world/Village";
import { Conversation } from "./Conversation";
import { GameOver } from "./GameOver";
import { WorldHealth } from "./WorldHealth";
import { useGame, useScore } from "./score";
import { EntityPanel } from "./EntityPanel";
import { EventSidebar } from "./EventSidebar";
import {
  useChronicleView,
  useFightChronicle,
  useLiveChronicle,
  useSampleClock,
} from "./feed";
import { useFights } from "../world/fights";
import { useMeetings } from "../world/meetings";
import { GodBar } from "./GodBar";
import { Header } from "./Header";
import { useSimulation } from "./useSimulation";

/** Full-screen village. Interface panels float over it as HUDs. */
export function App() {
  const update = useWorld((s) => s.update);
  const epoch = useWorld((s) => s.epoch);
  const sim = useSimulation();
  const sidebar = useChronicleView((s) => s.sidebar);
  // Live, the chronicle and fights follow the backend's events; offline
  // previews (no agents) fall back to hard-coded samples and scripted fights.
  const live = sim.mode === "live";
  useSampleClock(sim.mode === "offline");
  useFightChronicle(sim.mode === "offline");
  useLiveChronicle(live);
  useGame(tierOf, tierName);
  // The point of no return stops the clock; the player decides what next.
  const lost = useScore((s) => !!s.lost && !s.dismissed);
  useEffect(() => {
    if (lost) void sim.setPlayback(false, sim.speed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lost]);
  // Scripted fights and chats only in the offline preview, never live.
  const offline = sim.mode === "offline";
  useEffect(() => {
    useFights.setState({ scripted: offline });
    useMeetings.setState({ scripted: offline });
  }, [offline]);
  const [timelapse, setTimelapse] = useState(false);
  // Pause freezes the village too (stores/world.ts › usePlayback).
  useEffect(() => {
    const paused = sim.mode !== "loading" && !sim.playing;
    usePlayback.setState({ paused });
    // Scenes already under way end at once; waiting ones start after play.
    if (paused) {
      useMeetings.setState({ active: [] });
      useFights.setState({ current: null });
    }
  }, [sim.mode, sim.playing]);
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

  const day = String(update.state.tick + 1).padStart(2, "0");
  const status = !live
    ? sim.preview || "Offline preview · a scripted story"
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
    // The slow orbit plays at the current speed; it never changes it.
    if (next && !sim.playing) await sim.setPlayback(true, sim.speed);
  }

  return (
    <div className={`stage ${sidebar ? "with-sidebar" : ""}`}>
      <Village autoRotate={timelapse} />
      <Header tier={growth.name} />
      <GodBar live={live} onDecree={sim.intervene} />
      <EntityPanel live={live} />
      <EventSidebar />
      <Conversation live={live} />
      <GameOver onNewVillage={sim.newVillage} />
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
        <WorldHealth />
        <span className="hud-divider" />
        <button
          className="hud-button primary"
          aria-label={sim.playing ? "Pause simulation" : "Play simulation"}
          disabled={sim.mode === "loading" || (live && sim.busy)}
          onClick={() => {
            setTimelapse(false);
            void sim.togglePlay();
          }}
        >
          {sim.playing ? <Pause size={22} /> : <Play size={22} />}
        </button>
        <SpeedSlider
          value={sim.speed}
          disabled={sim.mode === "loading"}
          onChange={(speed) => sim.changeSpeed(speed)}
        />
        <button
          className={`hud-button ${timelapse ? "active" : ""}`}
          aria-label={timelapse ? "Stop time-lapse" : "Start time-lapse"}
          aria-pressed={timelapse}
          title="Time-lapse: a slow orbit around the town at the current speed"
          disabled={sim.mode === "loading" || (live && sim.busy)}
          onClick={() => void toggleTimelapse()}
        >
          <Clapperboard size={22} />
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

const SPEEDS = [1, 2, 4] as const;

/**
 * 1×, 2× or 4× as a three-stop slider. 1× is unhurried (a day takes
 * KRONOS_TICK_SECONDS, 30 s by default) so every event can be followed.
 */
function SpeedSlider({
  value,
  disabled,
  onChange,
}: {
  value: number;
  disabled: boolean;
  onChange: (speed: number) => void;
}) {
  const stop = Math.max(0, SPEEDS.indexOf(value as 1 | 2 | 4));
  return (
    <label className={`speed-slider ${disabled ? "disabled" : ""}`}>
      <span className="speed-value">{SPEEDS[stop]}×</span>
      <input
        type="range"
        min={0}
        max={2}
        step={1}
        value={stop}
        disabled={disabled}
        aria-label="Simulation speed"
        aria-valuetext={`${SPEEDS[stop]} times speed`}
        onChange={(e) => onChange(SPEEDS[Number(e.target.value)])}
      />
      <span className="speed-ticks" aria-hidden>
        {SPEEDS.map((s, i) => (
          <i key={s} className={i <= stop ? "on" : ""}>
            {s}×
          </i>
        ))}
      </span>
    </label>
  );
}

/** Growth tier for scoring (the same settled tier the town shows). */
const tierOf = (state: WorldState, epoch: number) =>
  growthOf(state, epoch).tier;
const tierName = (tier: number) => TIERS[tier];

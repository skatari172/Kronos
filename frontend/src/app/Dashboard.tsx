import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Boxes,
  ChevronRight,
  Circle,
  GitBranch,
  Globe2,
  Hourglass,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
  Sparkles,
  Sun,
} from "lucide-react";
import { context, connect, request } from "../api/client";
import type {
  Branch,
  InterventionResult,
  Snapshot,
  Status,
  WorldUpdate,
} from "../api/types";
import { usePresentation, useWorld } from "../stores/world";
import { Village } from "../world/Village";
import { Inspector } from "../components/Inspector";
import { coins } from "../api/format";
import { EventLedger } from "../components/EventLedger";

/**
 * The original full dashboard (panels, intervention, timeline). Not mounted
 * while the full-screen village is the main view; reuse its pieces as HUDs.
 */
export function Dashboard() {
  const update = useWorld((s) => s.update);
  const historical = useWorld((s) => s.historical);
  const [mode, setMode] = useState<"loading" | "live" | "offline">("loading");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [text, setText] = useState("");
  const demoIndex = useRef(0);
  const navigation = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let disconnect: (() => void) | undefined;
    async function load() {
      try {
        if (import.meta.env.DEV && import.meta.env.VITE_OFFLINE === "true")
          throw new Error("Offline requested");
        const world = await request<WorldUpdate>("/api/world");
        if (cancelled) return;
        useWorld.getState().replace(world);
        setMode("live");
        disconnect = connect(setConnected);
      } catch (e) {
        if (cancelled) return;
        if (import.meta.env.DEV) {
          const { initialMock } = await import("../api/mock");
          if (cancelled) return;
          useWorld.getState().replace(initialMock());
          setMode("offline");
        } else setError(`Cannot reach the village server. ${String(e)}`);
      }
    }
    void load();
    return () => {
      cancelled = true;
      disconnect?.();
    };
  }, []);

  const refreshHistory = useCallback(async (branchId: string) => {
    const [nextBranches, nextSnapshots] = await Promise.all([
      request<Branch[]>("/api/branches"),
      request<Snapshot[]>(
        `/api/history/snapshots?branch_id=${encodeURIComponent(branchId)}`,
      ),
    ]);
    if (useWorld.getState().update?.branch_id === branchId) {
      setBranches(nextBranches);
      setSnapshots(nextSnapshots);
    }
  }, []);
  useEffect(() => {
    if (mode !== "live" || !update) return;
    void refreshHistory(update.branch_id).catch((e) => setError(String(e)));
  }, [mode, update?.branch_id, update?.sequence, refreshHistory]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await request<Status>("/api/simulation/status");
        if (!cancelled) {
          setPlaying(status.playing);
          if (status.error) setError(status.error);
        }
      } catch {
        /* The socket connection badge communicates transport failure. */
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [mode]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function step() {
    const next = await request<WorldUpdate>("/api/simulation/tick", context());
    useWorld.getState().ingest(next);
  }
  async function playback() {
    const status = await request<Status>(
      playing ? "/api/simulation/pause" : "/api/simulation/play",
      { ...context(), speed },
    );
    setPlaying(status.playing);
  }
  async function intervene() {
    if (!text.trim()) return;
    const result = await request<InterventionResult>("/api/interventions", {
      ...context(),
      text,
    });
    useWorld.getState().ingest(result.update);
    setText("");
    const command = result.command;
    setNotice(
      command.type === "modify_price"
        ? `Bread prices changed by ${command.percent}% across all bakeries.`
        : `Intervention applied: ${command.type.replace("_", " ")}.`,
    );
  }
  async function seek(id: string) {
    const ticket = ++navigation.current;
    await request<Status>("/api/simulation/pause", {});
    setPlaying(false);
    useWorld.getState().replace(useWorld.getState().update!, true);
    const world = await request<WorldUpdate>(`/api/history/snapshots/${id}`);
    if (ticket === navigation.current) {
      useWorld.getState().replace(world, true);
      usePresentation.getState().select(null);
      setSnapshotId(id);
    }
  }
  async function activate(id: string) {
    const ticket = ++navigation.current;
    useWorld.getState().replace(useWorld.getState().update!, true);
    const world = await request<WorldUpdate>(
      `/api/branches/${id}/activate`,
      {},
    );
    if (ticket === navigation.current) {
      useWorld.getState().replace(world);
      usePresentation.getState().select(null);
      setSnapshotId("");
      setPlaying(false);
    }
  }
  async function fork() {
    const source = snapshotId || snapshots.at(-1)?.id;
    if (!source) throw new Error("No checkpoint available yet");
    const branch = await request<Branch>("/api/branches", {
      snapshot_id: source,
      name: `Alternate ${branches.length}`,
    });
    await activate(branch.id);
    await refreshHistory(branch.id);
    setNotice("A new timeline begins. The original history is preserved.");
  }
  async function demonstrate() {
    const { mockEvent } = await import("../api/mock");
    useWorld
      .getState()
      .ingest(mockEvent(useWorld.getState().update!, demoIndex.current++));
  }
  async function construct() {
    const state = useWorld.getState().update!.state;
    const builder = "citizen-1";
    // Town land, or a lot the builder owns or leases (others are `not_owner`).
    const plot = Object.values(state.plots).find(
      (p) =>
        !Object.values(state.buildings).some((b) => b.plot_id === p.id) &&
        (!p.owner_id || p.owner_id === builder || p.tenant_id === builder),
    );
    if (!plot) throw new Error("All construction plots are occupied");
    const result = await request<WorldUpdate>("/api/actions", {
      ...context(),
      action: {
        type: "construct_building",
        actor_id: builder,
        plot_id: plot.id,
        kind: "bakery",
        rationale: "Player requested a construction demonstration.",
      },
    });
    useWorld.getState().ingest(result);
  }
  if (!update)
    return (
      <main className="loading">
        <Hourglass size={36} />
        <h1>KRONOS</h1>
        <p>{error || "A small world is taking shape…"}</p>
        {error && <button onClick={() => location.reload()}>Reconnect</button>}
      </main>
    );
  const state = update.state;
  const citizens = Object.values(state.citizens);
  const avgHunger = Math.round(
    citizens.reduce((sum, c) => sum + c.hunger, 0) /
      Math.max(1, citizens.length),
  );
  const bread = Object.values(state.buildings).filter(
    (b) => b.kind === "bakery",
  );
  const locked = busy || historical || mode !== "live";
  const selectedSnapshot = snapshots.findIndex((s) => s.id === snapshotId);
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Hourglass size={22} />
          </span>
          KRONOS
          <span className="brand-divider" />
          <small>THE LIVING VILLAGE</small>
        </a>
        <div className="top-right">
          <span className={`connection ${connected ? "online" : ""}`}>
            <i />
            {mode === "offline"
              ? "OFFLINE DEMO"
              : connected
                ? "WORLD CONNECTED"
                : "RECONNECTING"}
          </span>
          <span className="version">EXPERIMENT 001</span>
        </div>
      </header>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">
            <Globe2 size={13} /> A WORLD OF POSSIBILITIES
          </div>
          <h1>
            Small village. <em>Infinite stories.</em>
          </h1>
        </div>
        <div className="branch-control">
          <GitBranch size={16} />
          <select
            aria-label="Active branch"
            disabled={busy || mode !== "live"}
            value={state.branch_id}
            onChange={(e) => void run(() => activate(e.target.value))}
          >
            {mode === "offline" ? (
              <option value="offline">Demo timeline</option>
            ) : (
              branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))
            )}
          </select>
        </div>
      </div>
      <main className="workspace">
        <div className="main-column">
          <section className="viewport">
            <div className="viewport-top">
              <span className="location">
                <i /> OAKHAVEN <small>EST. DAY 01</small>
              </span>
              <span className="season">
                <Sun size={15} /> Early autumn
              </span>
            </div>
            <Village />
            <div className="scene-hint">
              Drag to orbit <span>·</span> Scroll to explore <span>·</span>{" "}
              Click to inspect
            </div>
            <div className="scene-coordinate">
              47° N / 08° E <span>ILLUSTRATIVE WORLD</span>
            </div>
            <div className="world-caption">
              <span>YOUR LIVING WORLD</span>
              <h2>A new day in Oakhaven.</h2>
              <p>Watch the ordinary become extraordinary.</p>
            </div>
          </section>
          <section className="transport panel">
            <div className="day">
              <Sun size={21} />
              <div>
                <strong>
                  Day {state.tick + 1 < 10 ? "0" : ""}
                  {state.tick + 1}
                </strong>
                <small>
                  {historical
                    ? "Historical checkpoint"
                    : playing
                      ? "Life in motion"
                      : "A moment in time"}
                </small>
              </div>
            </div>
            <div className="playback">
              <button
                className="icon-button primary"
                aria-label={playing ? "Pause simulation" : "Play simulation"}
                disabled={locked}
                onClick={() => void run(playback)}
              >
                {playing ? <Pause size={17} /> : <Play size={17} />}
              </button>
              <button
                className="icon-button"
                aria-label="Advance one day"
                disabled={locked || playing}
                onClick={() => void run(step)}
              >
                <SkipForward size={18} />
              </button>
              <span className="thin-divider" />
              <select
                aria-label="Simulation speed"
                value={speed}
                disabled={busy || mode !== "live"}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  setSpeed(value);
                  if (playing)
                    void run(async () => {
                      await request("/api/simulation/play", {
                        ...context(),
                        speed: value,
                      });
                    });
                }}
              >
                <option value={1}>1× speed</option>
                <option value={2}>2× speed</option>
                <option value={4}>4× speed</option>
              </select>
            </div>
            <span className="paused-label">
              <Circle size={7} fill="currentColor" />
              {historical ? "PAST" : playing ? "PLAYING" : "PAUSED"}
            </span>
          </section>
          <section className="metrics">
            <div>
              <span>POPULATION</span>
              <strong>
                {citizens.length}
                <small>citizens</small>
              </strong>
            </div>
            <div>
              <span>BREAD PRICE</span>
              <strong>
                {coins(bread[0]?.prices.bread || 0)}
                <small>coins / loaf</small>
              </strong>
            </div>
            <div>
              <span>VILLAGE STOCK</span>
              <strong>
                {bread.reduce((sum, b) => sum + b.inventory.bread, 0)}
                <small>loaves</small>
              </strong>
            </div>
            <div>
              <span>AVG. HUNGER</span>
              <strong>
                {avgHunger}
                <small>/ 100</small>
              </strong>
            </div>
          </section>
          <section className="intervention panel">
            <div className="intervention-heading">
              <Sparkles size={18} />
              <h2>A small change. A different tomorrow.</h2>
              <span>YOUR INTERVENTION</span>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void run(intervene);
              }}
            >
              <input
                aria-label="Natural language intervention"
                placeholder="What would you change about this world?"
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={locked}
                maxLength={500}
              />
              <button
                aria-label="Apply intervention"
                className="submit"
                disabled={locked || !text.trim()}
              >
                <ArrowRight size={19} />
              </button>
            </form>
            <div className="suggestions">
              <span>TRY A CHANGE</span>
              <button
                disabled={locked}
                onClick={() => setText("Increase bread price by 40%.")}
              >
                Bread prices +40% <ChevronRight size={12} />
              </button>
              <button
                disabled={locked}
                onClick={() => setText("Decrease bread price by 20%.")}
              >
                Bread prices −20% <ChevronRight size={12} />
              </button>
            </div>
            <p className="scope-note">
              One-time change · all bakeries · future trades use the new price
            </p>
          </section>
          {(error || notice || mode === "offline" || historical) && (
            <div className={`notice ${error ? "error" : ""}`} role="status">
              {error ||
                notice ||
                (mode === "offline"
                  ? "Development preview · fixture data only. Start the API and reload to simulate, intervene, and save history."
                  : "Viewing a saved moment. Return to the present or fork this checkpoint to continue.")}
            </div>
          )}
          <section className="timeline panel">
            <div className="section-heading">
              <span>
                <GitBranch size={14} /> EXPLORE THE TIMELINE
              </span>
              <button
                disabled={busy || mode !== "live"}
                onClick={() => void run(() => activate(state.branch_id))}
              >
                <RotateCcw size={13} /> Present
              </button>
            </div>
            <div className="timeline-track">
              <span>ORIGIN</span>
              <input
                aria-label="Historical checkpoint"
                type="range"
                min={0}
                max={Math.max(0, snapshots.length - 1)}
                value={
                  selectedSnapshot < 0
                    ? Math.max(0, snapshots.length - 1)
                    : selectedSnapshot
                }
                disabled={busy || mode !== "live" || !snapshots.length}
                onChange={(e) => {
                  const snapshot = snapshots[Number(e.target.value)];
                  if (snapshot) void run(() => seek(snapshot.id));
                }}
              />
              <span>DAY {state.tick + 1}</span>
              <button
                className="fork-button"
                disabled={busy || mode !== "live" || !snapshots.length}
                onClick={() => void run(fork)}
              >
                <GitBranch size={14} /> Fork here
              </button>
            </div>
          </section>
        </div>
        <aside>
          <Inspector />
          <EventLedger />
          <div className="demo-card">
            <Boxes size={20} />
            <div>
              <strong>
                {mode === "offline"
                  ? "See the village evolve"
                  : "Room for another story"}
              </strong>
              <p>
                {mode === "offline"
                  ? "Cycle construction, upgrades, arrival, movement, prices, and departure."
                  : "Build a bakery on the next empty plot. Costs Marcus 50 coins."}
              </p>
              <button
                disabled={busy || historical || (mode !== "offline" && playing)}
                onClick={() =>
                  void run(mode === "offline" ? demonstrate : construct)
                }
              >
                {mode === "offline" ? "Next visual event" : "Build a bakery"}{" "}
                <ArrowRight size={13} />
              </button>
            </div>
          </div>
        </aside>
      </main>
      <footer>
        <span>
          OBSERVE <i>→</i> INTERVENE <i>→</i> EXPLORE
        </span>
        <span>Every choice leaves a trace.</span>
      </footer>
    </div>
  );
}

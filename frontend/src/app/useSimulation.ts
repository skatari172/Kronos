import { useEffect, useRef, useState } from "react";
import { connect, context, request, sendUserQuery } from "../api/client";
import type { Branch, Status, WorldUpdate } from "../api/types";
import { useWorld } from "../stores/world";

export type Mode = "loading" | "live" | "offline";

/**
 * Loads the world, keeps it synchronized, and exposes the playback controls.
 * In development without an API it falls back to the labeled fixture preview.
 */
/** One scripted story step every this many ms at 1× (offline preview). */
const OFFLINE_STEP_MS = 12_000;

export function useSimulation() {
  const [mode, setMode] = useState<Mode>("loading");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const demoIndex = useRef(0);
  const [preview, setPreview] = useState("");
  const autoplayed = useRef(false);

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

  // Playback is shared server state; another tab may start or pause it.
  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await request<Status>("/api/simulation/status");
        if (cancelled) return;
        // The village lives on its own: every visit starts with the clock
        // running. A pause during the visit is respected until the next load.
        if (!status.playing && !autoplayed.current && !status.error) {
          // Retried on the next poll if the world changed underneath (409).
          const started = await request<Status>("/api/simulation/play", {
            ...context(),
            speed: status.speed,
          });
          autoplayed.current = true;
          if (!cancelled) setPlaying(started.playing);
          return;
        }
        autoplayed.current = true;
        setPlaying(status.playing);
        setSpeed(status.speed);
        if (status.error) setError(status.error);
      } catch {
        /* The connection indicator communicates transport failure. */
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
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const step = () =>
    run(async () => {
      if (mode === "offline") {
        // Development preview only: plays the labeled fixture story, then
        // starts it over from the seed world.
        const { initialMock, mockEvent, STORY } = await import("../api/mock");
        const next = mockEvent(useWorld.getState().update!, demoIndex.current);
        if (next) {
          useWorld.getState().ingest(next);
          setPreview(
            `${STORY[demoIndex.current].title} · ${demoIndex.current + 1}/${STORY.length}`,
          );
          demoIndex.current++;
        } else {
          useWorld.getState().replace(initialMock());
          demoIndex.current = 0;
          setPreview("Story restarted from the seed village");
        }
        return;
      }
      const next = await request<WorldUpdate>(
        "/api/simulation/tick",
        context(),
      );
      useWorld.getState().ingest(next);
    });

  // Offline preview: the scripted story plays on its own, one step every
  // OFFLINE_STEP_MS at 1× (faster at 2× and 4×), like the live clock.
  useEffect(() => {
    if (mode === "offline") setPlaying(true);
  }, [mode]);
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    if (mode !== "offline" || !playing) return;
    const timer = setInterval(() => stepRef.current(), OFFLINE_STEP_MS / speed);
    return () => clearInterval(timer);
  }, [mode, playing, speed]);

  const togglePlay = () =>
    mode === "offline"
      ? setPlaying((p) => !p)
      : run(async () => {
          // Show the new state at once (a speed change right after Play must
          // see "playing"), then settle on what the backend reports.
          setPlaying(!playing);
          const status = await request<Status>(
            playing ? "/api/simulation/pause" : "/api/simulation/play",
            { ...context(), speed },
          );
          setPlaying(status.playing);
        });

  /**
   * Speak to the town in plain language (`POST /api/user/query`). The backend's
   * model picks one tool (an intervention, a citizen action, a new citizen,
   * the clock) and runs or queues it; the changed world then arrives over the
   * live connection like any other update. When no tool fits, the result is
   * `answered` with the town's reply and nothing changes. Throws with the
   * backend's reason when a chosen tool is rejected.
   */
  const intervene = async (text: string) => {
    // The model may take a few seconds; wait longer than usual.
    const outcome = await sendUserQuery(text);
    if (outcome.status === "rejected" || outcome.status === "error")
      throw new Error(
        outcome.error ?? "The town couldn't act on that. Try rewording it.",
      );
    return outcome;
  };

  /** Start the clock at a speed (used by time-lapse). */
  const setPlayback = (play: boolean, value: number) => {
    if (mode === "offline") {
      setSpeed(value);
      setPlaying(play);
      return Promise.resolve();
    }
    return run(async () => {
      setSpeed(value);
      const status = await request<Status>(
        play ? "/api/simulation/play" : "/api/simulation/pause",
        { ...context(), speed: value },
      );
      setPlaying(status.playing);
    });
  };

  /** Change speed at once; never locks the slider, and the latest choice wins. */
  const changeSpeed = (value: number) => {
    setSpeed(value);
    if (playing && mode === "live")
      void request<Status>("/api/simulation/play", {
        ...context(),
        speed: value,
      }).catch(() => {
        /* A stale world (409) is retried by the next change; the poll resyncs. */
      });
  };

  /**
   * Begin again with a fresh seed village. Live: the backend creates and
   * activates a new village (the old one stays in history), and the clock
   * starts. Offline: the preview story restarts from the seed.
   */
  const newVillage = () =>
    run(async () => {
      if (mode === "offline") {
        const { initialMock } = await import("../api/mock");
        useWorld.getState().replace(initialMock());
        demoIndex.current = 0;
        setPreview("A new village begins");
        setPlaying(true);
        return;
      }
      const village = await request<Branch>("/api/simulations", {});
      const world = await request<WorldUpdate>(
        `/api/branches/${village.id}/activate`,
        {},
      );
      useWorld.getState().replace(world);
      const status = await request<Status>("/api/simulation/play", {
        ...context(),
        speed,
      });
      setPlaying(status.playing);
    });

  return {
    mode,
    connected,
    newVillage,
    error,
    busy,
    playing,
    speed,
    step,
    preview,
    intervene,
    togglePlay,
    setPlayback,
    changeSpeed,
  };
}

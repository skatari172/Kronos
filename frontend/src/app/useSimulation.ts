import { useEffect, useRef, useState } from "react";
import { connect, context, request } from "../api/client";
import type { Status, WorldUpdate } from "../api/types";
import { useWorld } from "../stores/world";

export type Mode = "loading" | "live" | "offline";

/**
 * Loads the world, keeps it synchronized, and exposes the playback controls.
 * In development without an API it falls back to the labeled fixture preview.
 */
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
        // The village lives on its own: start the clock once per visit.
        // A later pause by anyone is respected.
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

  const togglePlay = () =>
    run(async () => {
      const status = await request<Status>(
        playing ? "/api/simulation/pause" : "/api/simulation/play",
        { ...context(), speed },
      );
      setPlaying(status.playing);
    });

  /** Start the clock at a speed (used by time-lapse). */
  const setPlayback = (play: boolean, value: number) =>
    run(async () => {
      setSpeed(value);
      const status = await request<Status>(
        play ? "/api/simulation/play" : "/api/simulation/pause",
        { ...context(), speed: value },
      );
      setPlaying(status.playing);
    });

  const changeSpeed = (value: number) => {
    setSpeed(value);
    if (playing)
      void run(async () => {
        await request("/api/simulation/play", { ...context(), speed: value });
      });
  };

  return {
    mode,
    connected,
    error,
    busy,
    playing,
    speed,
    step,
    preview,
    togglePlay,
    setPlayback,
    changeSpeed,
  };
}

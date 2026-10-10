import type { WorldUpdate } from "./types";
import { useWorld } from "../stores/world";

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
/** `timeoutMs` defaults to 8 s; calls that wait on an AI model pass more. */
export async function request<T>(
  path: string,
  body?: unknown,
  timeoutMs = 8000,
): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Invalid command. Check its values.",
    );
  }
  return response.json() as Promise<T>;
}

export function context() {
  const state = useWorld.getState().update;
  if (!state) throw new Error("World is still loading");
  return { branch_id: state.branch_id, expected_sequence: state.sequence };
}

export function connect(onConnection: (connected: boolean) => void) {
  let disposed = false;
  let socket: WebSocket | undefined;
  let timer: ReturnType<typeof setTimeout>;
  let attempts = 0;
  function open() {
    if (disposed) return;
    socket = new WebSocket(`${API.replace(/^http/, "ws")}/ws/world`);
    socket.onopen = async () => {
      attempts = 0;
      // HTTP resync on every reconnect. Epoch check prevents an old request undoing a seek.
      const { epoch } = useWorld.getState();
      try {
        const update = await request<WorldUpdate>("/api/world");
        if (disposed) return;
        const store = useWorld.getState();
        if (store.epoch === epoch && !store.historical) {
          if (store.update?.branch_id !== update.branch_id)
            store.replace(update);
          else store.ingest(update);
        }
        onConnection(true);
      } catch {
        onConnection(false);
      }
    };
    socket.onmessage = (message) => {
      try {
        const update = JSON.parse(message.data) as WorldUpdate;
        if (
          !update.state ||
          update.sequence !== update.state.sequence ||
          update.branch_id !== update.state.branch_id
        )
          return;
        useWorld.getState().ingest(update);
      } catch {
        /* Ignore malformed transport frames; reconnect uses HTTP truth. */
      }
    };
    socket.onclose = () => {
      onConnection(false);
      if (!disposed)
        timer = setTimeout(open, Math.min(1000 * 2 ** attempts++, 10000));
    };
    socket.onerror = () => socket?.close();
  }
  open();
  return () => {
    disposed = true;
    clearTimeout(timer);
    socket?.close();
  };
}

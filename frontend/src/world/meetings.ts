/**
 * Village conversations. Live, each agent message, friendly gesture, trade or
 * loan offer (from the backend's events) is staged as a meeting: both
 * villagers walk to a spot on the road between them, face each other, and
 * talk with a speech bubble over the one who started it. Clicking the bubble
 * opens the conversation (app/Conversation.tsx). Offline previews, which have
 * no agents, stage an occasional scripted chat instead.
 */
import { create } from "zustand";
import type { Pose } from "./Models";
import { nearestRoad, type Point, type Town } from "./town";
import type { Step } from "./fights";

export type TalkKind = "talk" | "friend" | "gift" | "deal" | "loan";

export type Talk = {
  kind: TalkKind;
  /** Short text for the speech bubble. */
  bubble: string;
  /** Words actually said (agent messages); otherwise an action is told. */
  line?: string;
  /** What happened, when nothing was said aloud ("offers a trade: …"). */
  action?: string;
  /** The speaker's private reasoning and who decided it. */
  reason: string;
  source: string;
  day: number;
};

export type Meeting = {
  id: number;
  a: string;
  b: string;
  at: Point;
  /** performance.now() when they start talking, and when they part. */
  startAt: number;
  endAt: number;
  talk: Talk;
};

/** How long a conversation plays, and how long the bubble lingers after. */
export const TALK_SECONDS = 10;
export const LINGER_SECONDS = 5;
const MAX_ACTIVE = 2;
const MAX_PENDING = 4;

/** Gestures for the speaker (a) and the listener (b), from the start of talk. */
const TALK_STEPS: Record<TalkKind, Record<"a" | "b", [Pose, number][]>> = {
  talk: {
    a: [
      ["wave", 1.4],
      ["talk", 2.4],
      ["idleB", 1.6],
      ["talk", 2.6],
    ],
    b: [
      ["idle", 1.6],
      ["idleB", 2.2],
      ["talk", 2.2],
      ["wave", 2],
    ],
  },
  friend: {
    a: [
      ["wave", 1.6],
      ["talk", 2.4],
      ["cheer", 2],
      ["idle", 2],
    ],
    b: [
      ["idle", 1.6],
      ["wave", 2],
      ["cheer", 2.4],
      ["idle", 2],
    ],
  },
  gift: {
    a: [
      ["wave", 1.2],
      ["give", 2.6],
      ["talk", 2.2],
      ["idle", 2],
    ],
    b: [
      ["idle", 1.8],
      ["pickup", 2],
      ["cheer", 2.4],
      ["idle", 1.8],
    ],
  },
  deal: {
    a: [
      ["talk", 2.4],
      ["give", 2.2],
      ["idleB", 1.6],
      ["talk", 1.8],
    ],
    b: [
      ["idleB", 2.4],
      ["talk", 2.4],
      ["idle", 1.4],
      ["idleB", 1.8],
    ],
  },
  loan: {
    a: [
      ["talk", 2.2],
      ["give", 2.4],
      ["idleB", 1.6],
      ["idle", 1.8],
    ],
    b: [
      ["idle", 2],
      ["talk", 2.4],
      ["pickup", 1.8],
      ["wave", 1.8],
    ],
  },
};

export function talkSteps(kind: TalkKind, role: "a" | "b"): Step[] {
  const steps = TALK_STEPS[kind][role];
  // Stretch the gestures to fill the whole conversation.
  const total = steps.reduce((sum, [, seconds]) => sum + seconds, 0);
  return steps.map(([pose, seconds]) => ({
    pose,
    seconds: (seconds * TALK_SECONDS) / total,
  }));
}

type Meetings = {
  active: Meeting[];
  pending: { a: string; b: string; talk: Talk }[];
  /** Offline previews script a chat now and then; live ones follow events. */
  scripted: boolean;
  nextScriptAt: number;
  /** The conversation open in the window, if any. */
  open: Meeting | null;
  request: (a: string, b: string, talk: Talk) => void;
  show: (meeting: Meeting | null) => void;
};

export const useMeetings = create<Meetings>((set) => ({
  active: [],
  pending: [],
  // Off until the app knows it is an offline preview (App.tsx turns it on).
  scripted: false,
  nextScriptAt: performance.now() + 9_000,
  open: null,
  request: (a, b, talk) =>
    set((s) =>
      a === b || s.pending.length >= MAX_PENDING
        ? s
        : { pending: [...s.pending, { a, b, talk }] },
    ),
  show: (open) => set({ open }),
}));

/** This villager's part in a current meeting, if any. */
export function meetingFor(citizenId: string) {
  const now = performance.now();
  const meeting = useMeetings
    .getState()
    .active.find(
      (m) => (m.a === citizenId || m.b === citizenId) && m.endAt > now,
    );
  if (!meeting) return undefined;
  const role = meeting.a === citizenId ? "a" : "b";
  const side = role === "a" ? -1 : 1;
  return {
    meeting,
    role,
    spot: { x: meeting.at.x + side * 0.36, z: meeting.at.z + 0.04 * side },
    other: { x: meeting.at.x - side * 0.36, z: meeting.at.z },
  } as const;
}

/** Everyone currently in a meeting (fights leave them be). */
export function meetingBusy() {
  const now = performance.now();
  return new Set(
    useMeetings
      .getState()
      .active.filter((m) => m.endAt > now)
      .flatMap((m) => [m.a, m.b]),
  );
}

/** HARD-CODED chats for offline previews, which have no agents. */
const SCRIPTED: Omit<Talk, "day">[] = [
  {
    kind: "talk",
    bubble: "Bread's gone up again…",
    line: "Bread's gone up again. Have you noticed?",
    reason: "If enough of us grumble, maybe the baker listens.",
    source: "Preview",
  },
  {
    kind: "friend",
    bubble: "Good to see you!",
    line: "Good to see you! Walk with me to the well?",
    reason: "A friend in town makes the hard days easier.",
    source: "Preview",
  },
  {
    kind: "deal",
    bubble: "Wheat for coin?",
    action: "offers two sacks of wheat for three coins",
    reason: "I have more wheat than I can use before it spoils.",
    source: "Preview",
  },
  {
    kind: "gift",
    bubble: "For you",
    action: "hands over a fresh loaf",
    reason: "They looked hungry this morning.",
    source: "Preview",
  },
];

/**
 * Start waiting meetings when the people are free (about once a second).
 * `citizens` are everyone in the scene; `busy` are ids that can't talk now.
 */
export function directMeetings(
  citizens: { id: string; x: number; z: number }[],
  town: Town,
  busy: Set<string>,
  day: number,
) {
  const now = performance.now();
  const state = useMeetings.getState();
  const active = state.active.filter(
    (m) => m.endAt + LINGER_SECONDS * 1000 > now,
  );
  let pending = state.pending;
  const taken = new Set([...busy, ...active.flatMap((m) => [m.a, m.b])]);
  const where = new Map(citizens.map((c) => [c.id, c]));
  const started: Meeting[] = [];

  const begin = (a: string, b: string, talk: Talk) => {
    const [pa, pb] = [where.get(a)!, where.get(b)!];
    const middle = { x: (pa.x + pb.x) / 2, z: (pa.z + pb.z) / 2 };
    const road = town.roads.get(nearestRoad(town, middle));
    if (!road) return;
    // Time to walk over: farther apart, longer to gather (4–9 s).
    const apart = Math.hypot(pa.x - pb.x, pa.z - pb.z);
    const startAt = now + Math.min(9, Math.max(4, apart * 0.9)) * 1000;
    started.push({
      id: Math.round(now) + started.length,
      a,
      b,
      at: road.at,
      startAt,
      endAt: startAt + TALK_SECONDS * 1000,
      talk,
    });
    taken.add(a).add(b);
  };

  while (pending.length && active.length + started.length < MAX_ACTIVE) {
    const [next, ...rest] = pending;
    pending = rest;
    // Someone left, or is fighting or already talking: let this one go.
    if (!where.has(next.a) || !where.has(next.b)) continue;
    if (taken.has(next.a) || taken.has(next.b)) continue;
    begin(next.a, next.b, next.talk);
  }

  let nextScriptAt = state.nextScriptAt;
  if (
    state.scripted &&
    now > nextScriptAt &&
    active.length + started.length === 0 &&
    citizens.length >= 2
  ) {
    const free = citizens.filter((c) => !taken.has(c.id));
    if (free.length >= 2) {
      const [a, b] = [...free].sort(() => Math.random() - 0.5);
      const sample = SCRIPTED[Math.floor(Math.random() * SCRIPTED.length)];
      begin(a.id, b.id, { ...sample, day });
    }
    nextScriptAt = now + 20_000 + Math.random() * 15_000;
  }

  if (
    started.length ||
    pending !== state.pending ||
    active.length !== state.active.length ||
    nextScriptAt !== state.nextScriptAt
  )
    useMeetings.setState({
      active: [...active, ...started],
      pending,
      nextScriptAt,
    });
}

/**
 * What floats over villagers: the speech bubble while they talk (click it to
 * open the conversation), the listener's reaction, and thought pops when their
 * agent acts. Plain DOM in one layer over the canvas (`OverlayLayer`);
 * `OverlayProjector`, inside the canvas, moves each element over its
 * villager's head every frame. One layer, no per-element React roots.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Vector3 } from "three";
import {
  Ban,
  Croissant,
  FileText,
  Gift,
  Hammer,
  Handshake,
  Heart,
  Home,
  Lightbulb,
  MessageCircle,
  Coins,
  PartyPopper,
  Tag,
  Target,
  Vote,
  type LucideIcon,
} from "lucide-react";
import { usePlayback } from "../stores/world";
import { physique } from "./assets";
import { crowdAt } from "./crowd";
import { EMOTE_SECONDS, useEmotes, type EmoteIcon } from "./emotes";
import {
  LINGER_SECONDS,
  TALK_SECONDS,
  useMeetings,
  type Meeting,
  type TalkKind,
} from "./meetings";

const EMOTE_ICONS: Record<EmoteIcon, LucideIcon> = {
  bread: Croissant,
  job: FileText,
  hired: PartyPopper,
  price: Tag,
  coins: Coins,
  no: Ban,
  build: Hammer,
  home: Home,
  goal: Target,
  idea: Lightbulb,
  vote: Vote,
  arrive: PartyPopper,
};

const TALK_ICONS: Record<TalkKind, LucideIcon> = {
  talk: MessageCircle,
  friend: Heart,
  gift: Gift,
  deal: Handshake,
  loan: Coins,
};

/** How the listener seems to take it, shown mid-conversation. */
const REACTIONS: Record<TalkKind, LucideIcon> = {
  talk: MessageCircle,
  friend: Heart,
  gift: Heart,
  deal: Lightbulb,
  loan: Lightbulb,
};

/** True from `from` until `to` (performance.now() times), re-rendering at each edge. */
function useWindow(from: number, to: number) {
  const [, tick] = useState(0);
  useEffect(() => {
    const now = performance.now();
    const timers = [from, to]
      .filter((t) => t > now)
      .map((t) => setTimeout(() => tick((n) => n + 1), t - now + 20));
    return () => timers.forEach(clearTimeout);
  }, [from, to]);
  const now = performance.now();
  return now >= from && now < to;
}

/** Elements to keep over a villager's head: element → villager and lift. */
const anchors = new Map<HTMLElement, { id: string; lift: number }>();

/** Height of a villager's head, in world units. */
const headOf = (id: string) => 1.02 * physique(id).height;

/** Inside the canvas: place every anchored element over its villager. */
export function OverlayProjector() {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const point = useRef(new Vector3());
  useFrame(() => {
    for (const [element, { id, lift }] of anchors) {
      const at = crowdAt(id);
      if (!at) {
        element.style.visibility = "hidden";
        continue;
      }
      const p = point.current
        .set(at.x, headOf(id) + lift, at.z)
        .project(camera);
      const x = ((p.x + 1) / 2) * size.width;
      const y = ((1 - p.y) / 2) * size.height;
      element.style.visibility = "visible";
      element.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
    }
  });
  return null;
}

function Anchor({
  id,
  lift = 0,
  children,
}: {
  id: string;
  lift?: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    anchors.set(element, { id, lift });
    return () => void anchors.delete(element);
  }, [id, lift]);
  return (
    <div ref={ref} className="overlay-anchor" style={{ visibility: "hidden" }}>
      {children}
    </div>
  );
}

/** Outside the canvas: every bubble, reaction and pop currently showing. */
export function OverlayLayer() {
  const meetings = useMeetings((s) => s.active);
  const emotes = useEmotes((s) => s.byId);
  const paused = usePlayback((s) => s.paused);
  // Paused: the village holds still, so nothing floats over it either.
  if (paused) return null;
  return (
    <div className="overlay-layer">
      {meetings.map((m) => (
        <Talking key={`a${m.id}`} meeting={m} speaker />
      ))}
      {meetings.map((m) => (
        <Talking key={`b${m.id}`} meeting={m} speaker={false} />
      ))}
      {Object.entries(emotes).map(([id, emote]) => (
        <Pop key={`${id}:${emote.key}`} id={id} emoteKey={emote.key} />
      ))}
    </div>
  );
}

function Talking({ meeting, speaker }: { meeting: Meeting; speaker: boolean }) {
  const show = useMeetings((s) => s.show);
  const end = meeting.endAt + LINGER_SECONDS * 1000;
  const from = speaker
    ? meeting.startAt
    : meeting.startAt + (TALK_SECONDS / 2) * 1000;
  const visible = useWindow(from, end);
  if (!visible) return null;
  const Icon = speaker
    ? TALK_ICONS[meeting.talk.kind]
    : REACTIONS[meeting.talk.kind];
  return (
    <Anchor id={speaker ? meeting.a : meeting.b}>
      {speaker ? (
        <button
          className={`speech-bubble ${meeting.talk.kind}`}
          onClick={(e) => {
            e.stopPropagation();
            show(meeting);
          }}
          title="Open the conversation"
        >
          <Icon size={14} aria-hidden />
          <span>{meeting.talk.bubble}</span>
        </button>
      ) : (
        <span className={`speech-reaction ${meeting.talk.kind}`} aria-hidden>
          <Icon size={14} />
        </span>
      )}
    </Anchor>
  );
}

function Pop({ emoteKey, id }: { emoteKey: number; id: string }) {
  const emote = useEmotes((s) => s.byId[id]);
  const [born] = useState(() => performance.now());
  const visible = useWindow(born, born + EMOTE_SECONDS * 1000);
  if (!visible || !emote || emote.key !== emoteKey) return null;
  const Icon = EMOTE_ICONS[emote.icon];
  return (
    <Anchor id={id} lift={0.12}>
      <span className={`thought-pop ${emote.tone}`}>
        <Icon size={13} aria-hidden />
        {emote.text}
      </span>
    </Anchor>
  );
}

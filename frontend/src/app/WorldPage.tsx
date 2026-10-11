/**
 * The world, explained. Cards compare the town at its founding (the seed) with
 * today: population, businesses, homes, money, hunger, bread price, wages,
 * wheat and policies. Choosing one shows how it got here: every event since
 * the seed that changed it, day by day, with who did it and why. Live, the
 * history is read from `GET /api/events` from the first event; offline it is
 * the preview's own events. Nothing here is computed by the browser except
 * the summaries of the snapshot; the history is the backend's record.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Coins,
  Croissant,
  Factory,
  Hammer,
  Home,
  Landmark,
  Scale,
  Sparkles,
  Users,
  Utensils,
  Wheat,
  X,
  type LucideIcon,
} from "lucide-react";
import { request } from "../api/client";
import { coins, describeEvent } from "../api/format";
import { initialMock } from "../api/mock";
import type { SimulationEvent, WorldState } from "../api/types";
import { useWorld } from "../stores/world";
import { growthOf, TIERS } from "../world/progress";
import { rememberNames, splitRationale, toEntry } from "./chronicle";

type Stat = {
  key: string;
  label: string;
  icon: LucideIcon;
  /** The number behind the card, and how to show it. */
  measure: (s: WorldState) => number;
  show: (n: number) => string;
  /** Events that changed this part of the world. */
  changes: (e: SimulationEvent) => boolean;
  /** Whether a rise is bad news (hunger, bread price); colours the arrow. */
  lowerIsBetter?: boolean;
};

const avg = (values: number[]) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
const decree = (e: SimulationEvent, ...kinds: string[]) =>
  e.type === "intervention_applied" && kinds.includes(e.payload.kind);
const policy = (e: SimulationEvent, ...kinds: string[]) =>
  (e.type === "policy_changed" || e.type === "vote_closed") &&
  kinds.includes((e.payload as { kind?: string }).kind ?? "");

const STATS: Stat[] = [
  {
    key: "people",
    label: "Population",
    icon: Users,
    measure: (s) => Object.keys(s.citizens).length,
    show: (n) => `${n}`,
    changes: (e) =>
      e.type === "citizen_spawned" || e.type === "citizen_removed",
  },
  {
    key: "business",
    label: "Businesses",
    icon: Factory,
    measure: (s) => Object.keys(s.buildings).length,
    show: (n) => `${n}`,
    changes: (e) =>
      e.type === "building_constructed" ||
      e.type === "building_removed" ||
      e.type === "building_upgraded",
  },
  {
    key: "homes",
    label: "Homes rented",
    icon: Home,
    measure: (s) => Object.values(s.plots).filter((p) => p.tenant_id).length,
    show: (n) => `${n}`,
    changes: (e) =>
      e.type === "lot_leased" ||
      e.type === "tenant_evicted" ||
      e.type === "plot_opened",
  },
  {
    key: "money",
    label: "Villagers' money",
    icon: Coins,
    measure: (s) => Object.values(s.citizens).reduce((a, c) => a + c.money, 0),
    show: (n) => coins(n),
    changes: (e) =>
      decree(e, "grant_money") ||
      e.type === "loan_accepted" ||
      e.type === "loan_defaulted" ||
      e.type === "trade_accepted" ||
      e.type === "building_removed",
  },
  {
    key: "hunger",
    label: "Average hunger",
    icon: Utensils,
    measure: (s) => avg(Object.values(s.citizens).map((c) => c.hunger)),
    show: (n) => `${Math.round(n)} / 100`,
    lowerIsBetter: true,
    changes: (e) => decree(e, "adjust_hunger") || e.type === "citizen_removed",
  },
  {
    key: "bread",
    label: "Bread price",
    icon: Croissant,
    measure: (s) =>
      avg(
        Object.values(s.buildings)
          .filter((b) => b.kind === "bakery")
          .map((b) => b.prices.bread),
      ),
    show: (n) => coins(Math.round(n)),
    lowerIsBetter: true,
    changes: (e) =>
      (e.type === "price_changed" && e.payload.resource === "bread") ||
      decree(e, "modify_price") ||
      policy(e, "bread_price_cap"),
  },
  {
    key: "wages",
    label: "Daily wage",
    icon: Hammer,
    measure: (s) => avg(Object.values(s.buildings).map((b) => b.wage)),
    show: (n) => coins(Math.round(n)),
    changes: (e) =>
      e.type === "wage_changed" ||
      decree(e, "set_wage") ||
      policy(e, "min_wage"),
  },
  {
    key: "wheat",
    label: "Wheat in the field",
    icon: Wheat,
    measure: (s) => s.resources.wheat?.stock ?? 0,
    show: (n) => `${n}`,
    changes: (e) =>
      decree(e, "adjust_resource") || e.type === "invention_adopted",
  },
  {
    key: "policy",
    label: "Town policies",
    icon: Scale,
    measure: (s) => Object.values(s.policies).filter(Boolean).length,
    show: (n) => (n ? `${n} in force` : "None"),
    changes: (e) =>
      e.type === "policy_changed" ||
      e.type === "vote_proposed" ||
      e.type === "vote_closed" ||
      decree(e, "set_policy"),
  },
];

/** Most a timeline renders; older lines are summarised as a count. */
const SHOWN = 400;
/** Most history read (pages of 500). */
const MAX_EVENTS = 30_000;

async function fullHistory(sequence: number) {
  const events: SimulationEvent[] = [];
  let after = Math.max(0, sequence - MAX_EVENTS);
  while (after < sequence) {
    const page = await request<SimulationEvent[]>(
      `/api/events?after=${after}&limit=500`,
      undefined,
      15_000,
    );
    if (!page.length) break;
    events.push(...page);
    after = page[page.length - 1].sequence;
  }
  return events;
}

type Line = {
  id: string;
  day: number;
  text: string;
  reason: string;
  source: string;
  decree: boolean;
};

/** A plain sentence for an event, with who did it and why. */
function explain(event: SimulationEvent, world: WorldState): Line {
  const entry = toEntry(event, world);
  const decreed = event.type === "intervention_applied";
  const { source, reason } = splitRationale(event.rationale);
  return {
    id: event.id,
    day: event.tick,
    text: entry?.text ?? describeEvent(event, world),
    reason: decreed ? `You said: “${event.payload.text}”` : reason,
    source: decreed ? "Your decree" : event.rationale ? source : "",
    decree: decreed,
  };
}

export function WorldPage({ onClose }: { onClose: () => void }) {
  const world = useWorld((s) => s.update?.state);
  const storeEvents = useWorld((s) => s.events);
  const epoch = useWorld((s) => s.epoch);
  const seed = useMemo(() => initialMock().state, []);
  const [history, setHistory] = useState<SimulationEvent[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [chosen, setChosen] = useState<string>("everything");

  // Read the whole record once per opening (and again after a seek).
  const sequence = world?.sequence ?? 0;
  useEffect(() => {
    let gone = false;
    fullHistory(sequence)
      .then((events) => !gone && setHistory(events))
      .catch(() => !gone && setFailed(true));
    return () => {
      gone = true;
    };
    // Only on open or a new epoch; the page shows the record as of opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epoch]);

  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  // Offline (no backend) the request fails at once and the preview's own events are used.
  const events = failed ? storeEvents : history;
  const stat = STATS.find((s) => s.key === chosen);
  const lines = useMemo(() => {
    if (!world || !events) return [];
    rememberNames(world);
    return events
      .filter((e) => (stat ? stat.changes(e) : toEntry(e, world) !== null))
      .map((e) => explain(e, world));
  }, [events, world, stat]);

  if (!world) return null;
  const tier = growthOf(world, epoch).tier;
  const shown = lines.slice(-SHOWN);
  const days = new Map<number, Line[]>();
  for (const line of shown) {
    const day = days.get(line.day) ?? [];
    day.push(line);
    days.set(line.day, day);
  }

  return (
    <div
      className="world-page"
      role="dialog"
      aria-modal="true"
      aria-label="The world"
    >
      <div className="world-sheet">
        <header>
          <div>
            <h2>Oakhaven today</h2>
            <p>
              Day {world.tick + 1} · {TIERS[tier]} · founded with{" "}
              {Object.keys(seed.citizens).length} villagers and{" "}
              {Object.keys(seed.buildings).length} businesses
            </p>
          </div>
          <button className="panel-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="world-body">
          <section
            className="world-stats"
            aria-label="The town now and at its founding"
          >
            <button
              className={`world-card everything ${chosen === "everything" ? "active" : ""}`}
              onClick={() => setChosen("everything")}
            >
              <span className="world-card-icon">
                <Landmark size={18} aria-hidden />
              </span>
              <span className="world-card-label">Everything</span>
              <strong>{world.tick} days</strong>
              <small>All that happened since the founding</small>
            </button>
            {STATS.map((s) => {
              const now = s.measure(world);
              const then = s.measure(seed);
              const delta = now - then;
              const Icon = s.icon;
              return (
                <button
                  key={s.key}
                  className={`world-card ${chosen === s.key ? "active" : ""}`}
                  onClick={() => setChosen(s.key)}
                >
                  <span className="world-card-icon">
                    <Icon size={18} aria-hidden />
                  </span>
                  <span className="world-card-label">{s.label}</span>
                  <strong>{s.show(now)}</strong>
                  <small>
                    was {s.show(then)} at founding
                    {Math.abs(delta) > 0.5 && (
                      <em
                        className={
                          delta > 0 !== !!s.lowerIsBetter ? "up" : "down"
                        }
                      >
                        {delta > 0 ? "▲" : "▼"}
                      </em>
                    )}
                  </small>
                </button>
              );
            })}
          </section>

          <section className="world-story" aria-label="How we got here">
            <h3>
              How we got here
              <span>{stat ? stat.label : "Everything"}</span>
            </h3>
            {!events ? (
              <p className="panel-note">Reading the town&rsquo;s records…</p>
            ) : (
              <ol>
                <li className="world-day">
                  <h4>Day 0 · The founding</h4>
                  <p className="world-line seed">
                    <Sparkles size={14} aria-hidden />
                    Oakhaven begins: {Object.keys(seed.citizens).length}{" "}
                    villagers, {Object.keys(seed.buildings).length} businesses (
                    {Object.values(seed.buildings)
                      .map((b) => b.name)
                      .join(", ")}
                    ), bread at {coins(STATS[5].measure(seed))} and wages of{" "}
                    {coins(STATS[6].measure(seed))} a day.
                  </p>
                </li>
                {lines.length > SHOWN && (
                  <li className="panel-note">
                    {lines.length - SHOWN} earlier changes not shown.
                  </li>
                )}
                {[...days].map(([day, dayLines]) => (
                  <li key={day} className="world-day">
                    <h4>Day {day}</h4>
                    {dayLines.map((line) => (
                      <div
                        key={line.id}
                        className={`world-line ${line.decree ? "decree" : ""}`}
                      >
                        <span>{line.text}</span>
                        {line.reason && (
                          <p>
                            “{line.reason.replace(/^You said: “|”$/g, "")}”
                            {line.source && (
                              <em className="chip">{line.source}</em>
                            )}
                          </p>
                        )}
                      </div>
                    ))}
                  </li>
                ))}
                {!lines.length && (
                  <li className="panel-note">
                    {stat
                      ? `Nothing has changed the ${stat.label.toLowerCase()} yet.`
                      : "Nothing has happened yet."}
                  </li>
                )}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

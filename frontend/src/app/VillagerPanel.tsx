/**
 * Everything a player can learn about one villager, in five tabs:
 * Overview (numbers and what's on their mind), Activity (what they did and
 * why, with who decided), Mind (personality, goals, priorities, memories),
 * Ties (how they feel about others), and Ask (a question answered from their
 * own history by their agent). Live, the profile and history come from
 * `GET /api/agents/{id}` and `/history`, refreshed every day; offline
 * previews use the snapshot and the events in the store.
 */
import { useEffect, useState } from "react";
import { MessageCircleQuestion, Send } from "lucide-react";
import { request } from "../api/client";
import { coins, describeEvent } from "../api/format";
import type {
  Citizen,
  CitizenProfile,
  SimulationEvent,
  WorldState,
} from "../api/types";
import { splitRationale, toEntry } from "./chronicle";
import { citizenThought } from "./profiles";

const TABS = ["Overview", "Activity", "Mind", "Ties", "Ask"] as const;
type Tab = (typeof TABS)[number];

const GOALS = ["wealth", "influence", "safety", "reputation"] as const;

const name = (state: WorldState, id?: string | null) =>
  (id && (state.citizens[id]?.name ?? state.buildings[id]?.name)) || "—";

/** Profile and recent history for one citizen; refreshed when the day changes. */
function useAgent(id: string, tick: number, live: boolean) {
  const [data, setData] = useState<{
    id: string;
    profile?: CitizenProfile;
    history: SimulationEvent[];
  } | null>(null);
  useEffect(() => {
    if (!live) return;
    let gone = false;
    Promise.all([
      request<CitizenProfile>(`/api/agents/${id}`),
      request<SimulationEvent[]>(`/api/agents/${id}/history?limit=300`),
    ])
      .then(([profile, history]) => !gone && setData({ id, profile, history }))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [id, tick, live]);
  return data?.id === id ? data : null;
}

/** One line per thing that happened, newest first, with the villager's reason. */
function activityOf(
  citizen: Citizen,
  events: SimulationEvent[],
  state: WorldState,
) {
  const lines: {
    key: string;
    day: number;
    text: string;
    reason: string;
    source: string;
    mine: boolean;
  }[] = [];
  // One decision can emit several events (a message and the trust it built):
  // tell it once, by the event that reads best.
  const best = new Map<string, SimulationEvent>();
  for (const event of events)
    if (event.action_id && !best.has(event.action_id) && toEntry(event, state))
      best.set(event.action_id, event);
  const told = new Set<string>();
  for (const event of [...events].reverse()) {
    if (event.action_id) {
      if (told.has(event.action_id)) continue;
      const pick = best.get(event.action_id);
      if (pick && pick !== event) continue;
      if (
        !pick &&
        events.some(
          (e) => e.action_id === event.action_id && e.sequence > event.sequence,
        )
      )
        continue;
      told.add(event.action_id);
    }
    const entry = toEntry(event, state);
    const mine = event.actor_id === citizen.id;
    if (!entry && !(mine && event.rationale)) continue;
    const { source, reason } = splitRationale(mine ? event.rationale : null);
    lines.push({
      key: event.id,
      day: event.tick,
      text: entry?.text ?? describeEvent(event, state),
      reason,
      source: mine ? source : "",
      mine,
    });
    if (lines.length >= 14) break;
  }
  return lines;
}

export function VillagerPanel({
  citizen,
  state,
  events,
  live,
}: {
  citizen: Citizen;
  state: WorldState;
  events: SimulationEvent[];
  live: boolean;
}) {
  const [tab, setTab] = useState<Tab>("Overview");
  const agent = useAgent(citizen.id, state.tick, live);
  // Live history covers every day; the store only holds the latest events.
  const history = agent?.history ?? events;
  const activity = activityOf(citizen, history, state);
  const decisions = history.filter(
    (e) => e.actor_id === citizen.id && e.rationale?.startsWith("["),
  );
  const sources = new Map<string, number>();
  for (const e of decisions) {
    const { source } = splitRationale(e.rationale);
    sources.set(source, (sources.get(source) ?? 0) + 1);
  }
  const latest = activity.find((a) => a.mine && a.reason);
  const mind = latest
    ? { thought: latest.reason, source: latest.source }
    : citizen.memories.length
      ? { thought: citizen.memories.at(-1)!, source: "Memory" }
      : { thought: citizenThought(citizen.id), source: "" };

  return (
    <>
      <nav className="panel-tabs" role="tablist" aria-label="Villager details">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      {tab === "Overview" && (
        <Overview
          citizen={citizen}
          state={state}
          profile={agent?.profile}
          mind={mind}
        />
      )}

      {tab === "Activity" && (
        <>
          {sources.size > 0 && (
            <p className="panel-note">
              Decided by{" "}
              {[...sources].map(([source, n]) => `${source} ×${n}`).join(" · ")}
            </p>
          )}
          {activity.length ? (
            <ol className="panel-list">
              {activity.map((a) => (
                <li key={a.key}>
                  <div className="panel-list-head">
                    <span>{a.text}</span>
                    <small>Day {a.day}</small>
                  </div>
                  {a.reason && (
                    <p className="panel-reason">
                      “{a.reason}”
                      {a.source && <em className="chip">{a.source}</em>}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="panel-note">Nothing yet. Give it a day or two.</p>
          )}
        </>
      )}

      {tab === "Mind" && (
        <>
          <section className="panel-section">
            <h3>Personality</h3>
            <p className="panel-line">{citizen.personality}</p>
            <div className="panel-goals">
              {citizen.goals.map((g) => (
                <span className="chip" key={g}>
                  {g}
                </span>
              ))}
            </div>
          </section>
          <section className="panel-section">
            <h3>Priorities</h3>
            {GOALS.map((g) => (
              <Bar
                key={g}
                label={g}
                value={citizen.goal_weights[g]}
                max={100}
              />
            ))}
          </section>
          <section className="panel-section">
            <h3>Memories</h3>
            {citizen.memories.length ? (
              <ol className="panel-memories">
                {[...citizen.memories].reverse().map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ol>
            ) : (
              <p className="panel-note">No memories yet.</p>
            )}
            {citizen.memory_summary && (
              <p className="panel-note">{citizen.memory_summary}</p>
            )}
          </section>
        </>
      )}

      {tab === "Ties" && <Ties citizen={citizen} state={state} />}

      {tab === "Ask" && <Ask citizen={citizen} live={live} />}
    </>
  );
}

function Overview({
  citizen,
  state,
  profile,
  mind,
}: {
  citizen: Citizen;
  state: WorldState;
  profile?: CitizenProfile;
  mind: { thought: string; source: string };
}) {
  const home = Object.values(state.plots).find(
    (p) => p.tenant_id === citizen.id,
  );
  const owned = Object.values(state.plots).filter(
    (p) => p.owner_id === citizen.id,
  ).length;
  const business = Object.values(state.buildings).find(
    (b) => b.owner_id === citizen.id,
  );
  return (
    <>
      <dl className="stats">
        <Stat label="Coins" value={coins(citizen.money)} />
        <Stat
          label="Works at"
          value={
            citizen.employer_id ? name(state, citizen.employer_id) : "No job"
          }
        />
        <Stat
          label="Home"
          value={
            home
              ? `Rents from ${name(state, home.owner_id)}`
              : owned
                ? `Owns ${owned} lot${owned > 1 ? "s" : ""}`
                : "None"
          }
        />
        <Stat label="Bread" value={`${citizen.inventory.bread} loaves`} />
        {business && <Stat label="Owns" value={business.name} />}
        <Stat label="Reputation" value={`${citizen.reputation} / 100`} />
        {profile && (
          <>
            <Stat
              label="Influence"
              value={`${(profile.influence / 100).toFixed(1)}%`}
            />
            <Stat label="Standing" value={profile.wealth_tier} />
          </>
        )}
      </dl>
      <Bar label="Hunger" value={citizen.hunger} max={100} warn={70} />
      <blockquote>
        “{mind.thought}”{mind.source && <cite>{mind.source}</cite>}
      </blockquote>
    </>
  );
}

function Ties({ citizen, state }: { citizen: Citizen; state: WorldState }) {
  const ties = [...citizen.relationships]
    .filter((r) => state.citizens[r.citizen_id])
    .sort(
      (a, b) => Math.abs(b.trust) + b.grudge - (Math.abs(a.trust) + a.grudge),
    )
    .slice(0, 8);
  if (!ties.length)
    return (
      <p className="panel-note">
        {citizen.name} hasn't got to know anyone yet.
      </p>
    );
  return (
    <ol className="panel-ties">
      {ties.map((t) => (
        <li key={t.citizen_id}>
          <div className="panel-list-head">
            <strong>{name(state, t.citizen_id)}</strong>
            <span className="chip">{t.type}</span>
          </div>
          <Bar label="Trust" value={t.trust} max={100} signed />
          {t.grudge > 0 && (
            <Bar label="Grudge" value={t.grudge} max={100} warn={0} />
          )}
        </li>
      ))}
    </ol>
  );
}

function Ask({ citizen, live }: { citizen: Citizen; live: boolean }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{
    q: string;
    a: string;
    cited: number;
  }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!live)
    return (
      <p className="panel-note">
        Asking villagers needs the backend. Start it with{" "}
        <code>make backend</code>.
      </p>
    );
  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await request<{
        answer: string;
        cited_event_ids: string[];
      }>(`/api/agents/${citizen.id}/ask`, { question: q }, 30_000);
      setAnswer({ q, a: result.answer, cited: result.cited_event_ids.length });
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <form className="panel-ask" onSubmit={ask}>
        <MessageCircleQuestion size={18} aria-hidden />
        <input
          aria-label={`Ask ${citizen.name} a question`}
          placeholder={`Ask ${citizen.name} why…`}
          value={question}
          maxLength={300}
          disabled={busy}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button aria-label="Ask" disabled={busy || !question.trim()}>
          <Send size={16} />
        </button>
      </form>
      {busy && <p className="panel-note">{citizen.name} is thinking…</p>}
      {error && <p className="panel-note warn">{error}</p>}
      {answer && (
        <div className="panel-answer">
          <small>You asked: {answer.q}</small>
          <blockquote>
            “{answer.a}”
            <cite>
              From {answer.cited} event{answer.cited === 1 ? "" : "s"} in their
              history
            </cite>
          </blockquote>
        </div>
      )}
    </>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** A labelled bar; `signed` bars run from −max to +max around a centre line. */
function Bar({
  label,
  value,
  max,
  warn,
  signed,
}: {
  label: string;
  value: number;
  max: number;
  warn?: number;
  signed?: boolean;
}) {
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  return (
    <div className="panel-meter">
      <div>
        <span>{label}</span>
        <span>
          {value}
          {signed ? "" : ` / ${max}`}
        </span>
      </div>
      <div className={`meter-track ${signed ? "signed" : ""}`}>
        <i
          className={
            (warn !== undefined && value > warn) || (signed && value < 0)
              ? "warn"
              : ""
          }
          style={
            signed
              ? {
                  width: `${pct / 2}%`,
                  marginLeft: value < 0 ? `${50 - pct / 2}%` : "50%",
                }
              : { width: `${pct}%` }
          }
        />
      </div>
    </div>
  );
}

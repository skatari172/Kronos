import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeftRight,
  BookOpen,
  Coins,
  Crown,
  Hammer,
  Home,
  Hourglass,
  MessageCircle,
  Search,
  Swords,
  TrendingDown,
  UserPlus,
  X,
  type LucideIcon,
} from "lucide-react";
import { useChronicle, type FeedItem, type FeedKind } from "./feed";

const ICONS: Record<FeedKind, LucideIcon> = {
  build: Hammer,
  trade: ArrowLeftRight,
  people: UserPlus,
  talk: MessageCircle,
  price: Coins,
  job: Coins,
  home: Home,
  loss: TrendingDown,
  fight: Swords,
  decree: Crown,
};

/** Chronicle filters: label and the event kinds each one shows. */
const FILTERS: { label: string; kinds: FeedKind[] | null }[] = [
  { label: "All", kinds: null },
  { label: "Your decrees", kinds: ["decree"] },
  { label: "Trade", kinds: ["trade"] },
  { label: "Building", kinds: ["build"] },
  { label: "People", kinds: ["people"] },
  { label: "Fights", kinds: ["fight"] },
  { label: "Talk", kinds: ["talk"] },
  { label: "Money", kinds: ["price", "job"] },
  { label: "Homes", kinds: ["home"] },
  { label: "Losses", kinds: ["loss"] },
];

/** Top bar: brand, the town's tier, and the button that opens the chronicle. */
export function Header({ tier }: { tier: string }) {
  const events = useChronicle((s) => s.items);
  const [open, setOpen] = useState(false);
  // Events have increasing ids; count the ones newer than the last look.
  const newest = events[0]?.id ?? 0;
  const [seen, setSeen] = useState(newest);
  const unseen = open ? 0 : Math.max(0, newest - seen);

  return (
    <>
      <header className="town-header">
        <div className="town-brand">
          <span className="town-mark">
            <Hourglass size={16} />
          </span>
          <span className="town-name">KRONOS</span>
          <span className="town-tier">Oakhaven · {tier}</span>
        </div>
        <button
          className="chronicle-button"
          aria-expanded={open}
          onClick={() => {
            setSeen(newest);
            setOpen(!open);
          }}
        >
          <BookOpen size={17} />
          Chronicle
          {unseen > 0 && <span className="badge">{unseen}</span>}
        </button>
      </header>
      {open && (
        <Chronicle
          events={events}
          onClose={() => {
            setSeen(newest);
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

/**
 * The event stream as its own page. Filter by kind or search names and words;
 * clicking an event opens a box explaining why it happened, and the page
 * freezes behind it so nothing moves while someone is reading.
 */
function Chronicle({
  events,
  onClose,
}: {
  events: FeedItem[];
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<FeedItem | null>(null);
  const [frozen, setFrozen] = useState<FeedItem[] | null>(null);
  const [filter, setFilter] = useState(FILTERS[0]);
  const [query, setQuery] = useState("");
  const source = frozen ?? events;

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return source.filter(
      (e) =>
        (!filter.kinds || filter.kinds.includes(e.kind)) &&
        (!words ||
          e.text.toLowerCase().includes(words) ||
          e.why.some((w) => w.name.toLowerCase().includes(words))),
    );
  }, [source, filter, query]);

  const open = (event: FeedItem) => {
    setFrozen(events);
    setDetail(event);
  };
  const closeDetail = () => {
    setDetail(null);
    setFrozen(null);
  };

  useEffect(() => {
    // Esc closes the open box first, then the chronicle.
    const close = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (detail) {
        setDetail(null);
        setFrozen(null);
      } else onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [detail, onClose]);

  return (
    <div
      className="chronicle"
      role="dialog"
      aria-modal="true"
      aria-label="Chronicle"
      onClick={onClose}
    >
      <div className="chronicle-sheet" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h2>Chronicle</h2>
            <p>Click an event to see why it happened.</p>
          </div>
          <button
            className="panel-close"
            aria-label="Close chronicle"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>
        <div className="chronicle-tools">
          <label className="chronicle-search">
            <Search size={16} aria-hidden />
            <input
              aria-label="Search events"
              placeholder="Search people or events"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="chronicle-filters" role="group" aria-label="Filter">
            {FILTERS.map((f) => {
              const count = f.kinds
                ? source.filter((e) => f.kinds!.includes(e.kind)).length
                : source.length;
              return (
                <button
                  key={f.label}
                  className={`${f === filter ? "active" : ""} ${f.kinds?.includes("decree") ? "decree" : ""}`}
                  aria-pressed={f === filter}
                  onClick={() => setFilter(f)}
                >
                  {f.label}
                  <span>{count}</span>
                </button>
              );
            })}
          </div>
        </div>
        <ol>
          {shown.map((event, i) => {
            const Icon = ICONS[event.kind];
            return (
              <li
                key={event.id}
                className={`${event.kind} ${i === 0 && !frozen ? "newest" : ""}`}
              >
                <button className="chronicle-row" onClick={() => open(event)}>
                  <span className="chronicle-icon">
                    <Icon size={20} aria-hidden />
                  </span>
                  <span className="chronicle-text">
                    {event.kind === "decree" && (
                      <span className="decree-tag">Your decree</span>
                    )}
                    {event.text}
                  </span>
                  <span className="chronicle-day">Day {event.day}</span>
                </button>
              </li>
            );
          })}
          {!shown.length && (
            <li className="chronicle-empty">
              {filter.kinds?.includes("decree") && !query
                ? "No decrees yet. Speak to Oakhaven from the box above the town."
                : "No events match."}
            </li>
          )}
        </ol>
      </div>
      {detail && <WhyBox event={detail} onClose={closeDetail} />}
    </div>
  );
}

/** Why one event happened: each person involved, what they wanted, and why. */
function WhyBox({ event, onClose }: { event: FeedItem; onClose: () => void }) {
  const Icon = ICONS[event.kind];
  return (
    <div
      className="why-backdrop"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        className={`why-box ${event.kind}`}
        role="dialog"
        aria-modal="true"
        aria-label={event.text}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <span className="chronicle-icon">
            <Icon size={20} aria-hidden />
          </span>
          <div>
            <h3>{event.text}</h3>
            <span className="chronicle-day">Day {event.day}</span>
          </div>
          <button className="panel-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className={`why-sides ${event.why.length > 1 ? "two" : ""}`}>
          {event.why.map((side) => (
            <section key={side.name + side.role}>
              <header>
                <strong>{side.name}</strong>
                <span className="chip">{side.role}</span>
              </header>
              <dl>
                <dt>Wanted</dt>
                <dd>{side.incentive}</dd>
                <dt>Thinking</dt>
                <dd className="thought">“{side.thought}”</dd>
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

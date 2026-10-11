import { useState } from "react";
import { Heart, Star } from "lucide-react";
import { useWorld } from "../stores/world";
import { CRITICAL, CRITICAL_DAYS, health, useScore } from "./score";

/**
 * World Health and the score, in the bottom bar. Hover for what health is
 * made of, why it is low, and the latest points with their reasons.
 */
export function WorldHealth() {
  const state = useWorld((s) => s.update?.state);
  const points = useScore((s) => s.points);
  const ledger = useScore((s) => s.ledger);
  const critical = useScore((s) => s.criticalDays);
  const [open, setOpen] = useState(false);
  if (!state) return null;
  const h = health(state);
  const tone = h.value >= 60 ? "good" : h.value >= 30 ? "fair" : "poor";
  return (
    <div
      className="world-health"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        className={`health-pill ${tone}`}
        aria-label={`World Health ${h.value} of 100, score ${points}`}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="health-caption">
          <Heart size={14} aria-hidden />
          <span className="health-label">World Health</span>
        </span>
        <span className="health-caption">
          <Star size={13} aria-hidden />
          <span className="health-label">Score</span>
        </span>
        <span className="health-stat">
          <span className="health-bar">
            <i style={{ width: `${h.value}%` }} />
          </span>
          <strong>{h.value}</strong>
        </span>
        <span className="health-stat">
          <strong>{points.toLocaleString()}</strong>
        </span>
      </button>
      {open && (
        <div className="health-card" role="tooltip">
          <header>
            <strong>World Health {h.value}</strong>
            <small>
              {critical > 0
                ? `Critical for ${critical} of ${CRITICAL_DAYS} days: the town falls if it stays under ${CRITICAL}`
                : h.reasons.length
                  ? "What's holding Oakhaven back"
                  : "Oakhaven is thriving"}
            </small>
          </header>
          {h.reasons.length > 0 && (
            <ul className="health-reasons">
              {h.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
          <div className="health-parts">
            {h.parts.map((p) => (
              <div key={p.key}>
                <span>{p.label}</span>
                <span className="health-bar small">
                  <i
                    className={
                      p.value < 30 ? "poor" : p.value < 60 ? "fair" : ""
                    }
                    style={{ width: `${Math.max(2, Math.min(100, p.value))}%` }}
                  />
                </span>
                <em>{Math.round(Math.max(0, Math.min(100, p.value)))}</em>
              </div>
            ))}
          </div>
          <h4>
            Score <span>{points.toLocaleString()}</span>
          </h4>
          <p className="health-rules">
            Earn points each day from World Health, for newcomers, businesses,
            upgrades and new tiers. Lose them when people leave, businesses
            close, villagers quarrel, and each time you step in from above.
          </p>
          <ol className="health-ledger">
            {ledger.slice(0, 7).map((e) => (
              <li key={e.id}>
                <em className={e.delta >= 0 ? "up" : "down"}>
                  {e.delta >= 0 ? "+" : ""}
                  {e.delta}
                </em>
                <span>{e.reason}</span>
                <small>Day {e.day}</small>
              </li>
            ))}
            {!ledger.length && <li className="panel-note">No points yet.</li>}
          </ol>
        </div>
      )}
    </div>
  );
}

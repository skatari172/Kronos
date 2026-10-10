import { Activity, ArrowUpRight } from "lucide-react";
import { useWorld } from "../stores/world";
import { describeEvent } from "../api/format";
export function EventLedger() {
  const events = useWorld((s) => s.events);
  const world = useWorld((s) => s.update?.state);
  const important = events
    .filter(
      (e) =>
        e.type !== "citizen_moved" &&
        e.type !== "resource_consumed" &&
        e.type !== "tick_completed",
    )
    .slice(-40)
    .reverse();
  return (
    <section className="ledger panel">
      <div className="section-heading">
        <span>THE CHRONICLE</span>
        <Activity size={15} />
      </div>
      <div className="ledger-title">
        <h2>History in the making</h2>
        <span>{events.length} events</span>
      </div>
      <div className="event-list">
        {important.length ? (
          important.map((e) => (
            <details className="event" key={e.id}>
              <summary>
                <i
                  className={
                    e.type === "price_changed" ||
                    e.type === "intervention_applied"
                      ? "gold"
                      : ""
                  }
                />
                <div>
                  <small>
                    DAY {e.tick + 1} <span>#{e.sequence}</span>
                  </small>
                  <p>{describeEvent(e, world)}</p>
                </div>
                <ArrowUpRight size={13} />
              </summary>
              <div className="event-detail">
                {e.rationale && <p>Agent-stated rationale: {e.rationale}</p>}
                <pre>{JSON.stringify(e, null, 2)}</pre>
              </div>
            </details>
          ))
        ) : (
          <div className="quiet">
            <span>◷</span>
            <p>The village is waking up.</p>
            <small>Advance a day or make your first intervention.</small>
          </div>
        )}
      </div>
    </section>
  );
}

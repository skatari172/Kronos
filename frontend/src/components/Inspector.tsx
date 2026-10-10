import { Building2, CircleUserRound, MousePointer2 } from "lucide-react";
import { usePresentation, useWorld } from "../stores/world";
import { coins } from "../api/format";
export function Inspector() {
  const state = useWorld((s) => s.update!.state);
  const selected = usePresentation((s) => s.selectedId);
  const citizen = selected ? state.citizens[selected] : undefined;
  const building = selected ? state.buildings[selected] : undefined;
  return (
    <section className="inspector panel">
      <div className="section-heading">
        <span>FIELD NOTES</span>
        <MousePointer2 size={14} />
      </div>
      {!citizen && !building ? (
        <div className="empty-inspector">
          <div className="icon-ring">
            <MousePointer2 size={24} />
          </div>
          <h3>Every life has a story.</h3>
          <p>
            Select a citizen or building in the village to look a little closer.
          </p>
          <div className="village-facts">
            <span>{Object.keys(state.citizens).length} citizens</span>
            <span>{Object.keys(state.buildings).length} buildings</span>
          </div>
        </div>
      ) : citizen ? (
        <>
          <div className="entity-heading">
            <CircleUserRound size={30} />
            <div>
              <h2>{citizen.name}</h2>
              <p>
                {citizen.occupation} · {citizen.personality}
              </p>
            </div>
          </div>
          <dl>
            <div>
              <dt>Savings</dt>
              <dd>{coins(citizen.money)} coins</dd>
            </div>
            <div>
              <dt>Food</dt>
              <dd>{citizen.inventory.bread} bread</dd>
            </div>
            <div>
              <dt>Hunger</dt>
              <dd>{citizen.hunger}%</dd>
            </div>
          </dl>
          <div className="meter">
            <span style={{ width: `${citizen.hunger}%` }} />
          </div>
          <h4>PERSONAL GOALS</h4>
          {citizen.goals.map((goal) => (
            <p className="note" key={goal}>
              ↗ {goal}
            </p>
          ))}
          <h4>RECENT MEMORIES</h4>
          {citizen.memories.length ? (
            citizen.memories.map((memory, i) => (
              <p className="note" key={i}>
                {memory}
              </p>
            ))
          ) : (
            <p className="muted">A new day, an unwritten story.</p>
          )}
          {citizen.relationships.map((r) => (
            <p key={r.citizen_id} className="note">
              Trust in {state.citizens[r.citizen_id]?.name}: {r.trust}
            </p>
          ))}
        </>
      ) : (
        building && (
          <>
            <div className="entity-heading">
              <Building2 size={30} />
              <div>
                <h2>{building.name}</h2>
                <p>
                  {building.kind} · Level {building.level}
                </p>
              </div>
            </div>
            <dl>
              <div>
                <dt>Owner</dt>
                <dd>{state.citizens[building.owner_id]?.name}</dd>
              </div>
              <div>
                <dt>Business cash</dt>
                <dd>{coins(building.cash)} coins</dd>
              </div>
              <div>
                <dt>Bread</dt>
                <dd>{building.inventory.bread} loaves</dd>
              </div>
              <div>
                <dt>Wheat</dt>
                <dd>{building.inventory.wheat} sacks</dd>
              </div>
              <div>
                <dt>Bread price</dt>
                <dd>{coins(building.prices.bread)} coins</dd>
              </div>
            </dl>
            <p className="note">
              Prices belong to this business. Stock and cash change as the
              village trades.
            </p>
          </>
        )
      )}
    </section>
  );
}

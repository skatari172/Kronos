import { RotateCcw, Skull } from "lucide-react";
import { useWorld } from "../stores/world";
import { useScore } from "./score";

/** The point of no return: Oakhaven has fallen. */
export function GameOver({
  onNewVillage,
}: {
  onNewVillage: () => Promise<void> | void;
}) {
  const lost = useScore((s) => s.lost);
  const dismissed = useScore((s) => s.dismissed);
  const points = useScore((s) => s.points);
  const peak = useScore((s) => s.peakPopulation);
  const state = useWorld((s) => s.update?.state);
  if (!lost || dismissed || !state) return null;
  return (
    <div
      className="game-over"
      role="alertdialog"
      aria-modal="true"
      aria-label="Oakhaven has fallen"
    >
      <div className="game-over-card">
        <span className="game-over-icon">
          <Skull size={30} aria-hidden />
        </span>
        <small>
          Day {lost.day} · {lost.reason}
        </small>
        <h2>Oakhaven has fallen</h2>
        <p>{lost.detail}</p>
        <dl>
          <div>
            <dt>Days survived</dt>
            <dd>{lost.day}</dd>
          </div>
          <div>
            <dt>Peak population</dt>
            <dd>{peak}</dd>
          </div>
          <div>
            <dt>Final score</dt>
            <dd>{points.toLocaleString()}</dd>
          </div>
        </dl>
        <div className="game-over-actions">
          <button
            className="game-over-primary"
            onClick={() => void onNewVillage()}
          >
            <RotateCcw size={16} aria-hidden /> Start a new village
          </button>
          <button
            className="game-over-secondary"
            onClick={() => useScore.setState({ dismissed: true })}
          >
            Keep watching
          </button>
        </div>
      </div>
    </div>
  );
}

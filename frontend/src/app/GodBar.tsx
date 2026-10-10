import { useState } from "react";
import { ArrowRight, Sparkles, TriangleAlert } from "lucide-react";
import type { InterventionResult } from "../api/types";
import { useWorld } from "../stores/world";
import { useDecrees } from "../world/decrees";
import { useChronicle } from "./feed";
import {
  describe,
  EXAMPLES,
  previewCommand,
  reactionTo,
  type Command,
} from "./rules";

/** Time for a decree to drift from the sky onto the town, in ms. */
const FALL_MS = 2600;

type Falling = { id: number; text: string };

/**
 * The player speaks to the town from above. A rule the town understands
 * drifts down onto the village, strikes the square in gold (DecreeEffect in
 * the scene), and is written into the chronicle as a decree. Live, the rule is
 * applied by `POST /api/interventions`; offline, it is only previewed.
 */
export function GodBar({
  live,
  onDecree,
}: {
  live: boolean;
  onDecree: (text: string) => Promise<InterventionResult>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // Examples show when the box is clicked, and close once something is said.
  const [suggest, setSuggest] = useState(false);
  const [error, setError] = useState("");
  const [falling, setFalling] = useState<Falling[]>([]);

  async function speak(value = text) {
    const words = value.trim();
    if (!words || busy) return;
    setSuggest(false);
    setBusy(true);
    setError("");
    try {
      // Anything may be said. Live, the backend (and its AI model, when
      // configured) decides what it means; offline, known phrasings get an
      // exact summary and everything else is recorded in the player's words.
      const command: Command | null = live
        ? (await onDecree(words)).command
        : previewCommand(words);
      setText("");
      // Let go of the box so the words can be watched falling onto the town.
      (document.activeElement as HTMLElement | null)?.blur();
      const id = Date.now();
      setFalling((f) => [...f, { id, text: words }]);
      setTimeout(() => {
        setFalling((f) => f.filter((d) => d.id !== id));
        land(words, command, live);
      }, FALL_MS);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      // The backend lists its whole grammar on a miss; keep the message short.
      setError(
        message.startsWith("Supported:")
          ? "The town couldn't act on that. Try rewording it, or pick an example."
          : message.includes("aborted") || message.includes("timed out")
            ? "The town took too long to answer. Try again."
            : message,
      );
      setTimeout(() => setError(""), 5000);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div
        className={`god-bar ${error ? "rejected" : ""} ${busy ? "listening" : ""}`}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void speak();
          }}
        >
          <Sparkles size={18} aria-hidden />
          <input
            aria-label="Speak a decree to the town"
            placeholder={
              busy
                ? "The town is listening…"
                : "Speak to Oakhaven… say anything"
            }
            value={text}
            disabled={busy}
            maxLength={500}
            onChange={(e) => {
              setText(e.target.value);
              setError("");
            }}
            onFocus={() => setSuggest(true)}
            onClick={() => setSuggest(true)}
            onKeyDown={(e) => e.key === "Escape" && setSuggest(false)}
            onBlur={() => setTimeout(() => setSuggest(false), 150)}
          />
          <button
            className="god-submit"
            aria-label="Decree"
            disabled={busy || !text.trim()}
          >
            <ArrowRight size={18} />
          </button>
        </form>
        {!live && (
          <p className="god-note">
            Preview · the world changes once the backend is running
          </p>
        )}
        {suggest && !text && !busy && (
          <div className="god-examples" role="listbox" aria-label="Examples">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => void speak(example)}
              >
                {example}
              </button>
            ))}
          </div>
        )}
        {error && (
          <div className="god-error" role="status">
            <TriangleAlert size={16} />
            {error}
          </div>
        )}
      </div>
      {falling.map((decree) => (
        <div key={decree.id} className="decree-fall" aria-hidden>
          “{decree.text}”
        </div>
      ))}
    </>
  );
}

/** The decree lands: strike the town, then write it into the chronicle. */
function land(text: string, command: Command | null, live: boolean) {
  useDecrees.getState().land();
  const state = useWorld.getState().update?.state;
  useChronicle.getState().add({
    day: (state?.tick ?? 0) + 1,
    kind: "decree",
    text: command ? describe(command, state) : `“${text}”`,
    why: [
      {
        name: "You",
        role: live ? "Decree" : "Preview decree",
        incentive: "Shape the town from above",
        thought: text,
      },
      {
        name: "Oakhaven",
        role: "The town",
        incentive: "Live with the new rule",
        thought: command
          ? reactionTo(command)
          : "Villagers repeat your words to one another, unsure what comes next.",
      },
    ],
  });
}

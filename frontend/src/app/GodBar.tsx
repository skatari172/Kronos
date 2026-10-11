import { useState } from "react";
import { ArrowRight, Info, Sparkles, TriangleAlert, X } from "lucide-react";
import type { DeterminedToolCall, UserQueryResult } from "../api/types";
import { useWorld } from "../stores/world";
import { useDecrees } from "../world/decrees";
import { useChronicle } from "./feed";
import {
  commandOf,
  describe,
  describeTool,
  EXAMPLES,
  moodOf,
  previewCommand,
  reactionTo,
  toolMood,
  type Command,
} from "./rules";

/** Time for a decree to drift from the sky onto the town, in ms. */
const FALL_MS = 2600;
/** How long the "world has not changed" note stays up, in ms. */
const NOTICE_MS = 9000;

type Falling = { id: number; text: string };

/**
 * The player speaks to the town from above. A rule the town understands
 * drifts down onto the village, strikes the square in gold (DecreeEffect in
 * the scene), and is written into the chronicle as a decree. Live, the words go
 * to `POST /api/user/query`: the backend's model picks one tool and the world
 * changes through it, or, when no tool fits, the town answers in words and
 * nothing changes. Offline, decrees are only previewed.
 */
export function GodBar({
  live,
  onDecree,
}: {
  live: boolean;
  onDecree: (text: string) => Promise<UserQueryResult>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // Examples show when the box is clicked, and close once something is said.
  const [suggest, setSuggest] = useState(false);
  const [error, setError] = useState("");
  const [falling, setFalling] = useState<Falling[]>([]);
  // When the world didn't change (no tool fit, or the request failed): a
  // short-lived note with the reason. `key` restarts its timer and animation.
  const [notice, setNotice] = useState<{ key: number; text: string } | null>(
    null,
  );
  const unchanged = (text: string) => {
    const key = Date.now();
    setNotice({ key, text });
    setTimeout(() => setNotice((n) => (n?.key === key ? null : n)), NOTICE_MS);
  };

  async function speak(value = text) {
    const words = value.trim();
    if (!words || busy) return;
    setSuggest(false);
    setBusy(true);
    setError("");
    setNotice(null);
    try {
      // Anything may be said. Live, the backend's model decides what it means
      // and which tool to use; offline, known phrasings get an exact summary
      // and everything else is recorded in the player's words.
      let tool: DeterminedToolCall | null = null;
      let command: Command | null = null;
      if (live) {
        const outcome = await onDecree(words);
        if (outcome.status === "answered" || !outcome.tool_call) {
          // No tool fit: the town answers, and nothing changes.
          setText("");
          unchanged(outcome.message ?? "The town listens, but does nothing.");
          return;
        }
        tool = outcome.tool_call;
        command = commandOf(tool);
      } else command = previewCommand(words);
      setText("");
      // Let go of the box so the words can be watched falling onto the town.
      (document.activeElement as HTMLElement | null)?.blur();
      const id = Date.now();
      setFalling((f) => [...f, { id, text: words }]);
      useDecrees.getState().fall(FALL_MS);
      setTimeout(() => {
        setFalling((f) => f.filter((d) => d.id !== id));
        land(words, command, tool, live);
      }, FALL_MS);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      // The request always goes through; when it can't change anything, say why.
      setText("");
      unchanged(
        message.includes("aborted") || message.includes("timed out")
          ? "The town took too long to answer. Try again."
          : message.startsWith("Supported:") ||
              message.includes("invalid output")
            ? "The town couldn't make sense of that. Try rewording it."
            : message,
      );
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
          <PowersHint
            onPick={(example) => {
              setText(example);
              setSuggest(false);
            }}
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
        {notice && (
          <div className="god-notice" role="status" key={notice.key}>
            <Sparkles size={16} aria-hidden />
            <div>
              <small>World has not changed after this message:</small>
              <p>{notice.text}</p>
            </div>
            <button
              className="god-reply-close"
              aria-label="Dismiss"
              onClick={() => setNotice(null)}
            >
              <X size={15} />
            </button>
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

/**
 * The decree lands: strike the town, then write it into the chronicle. Live,
 * a town-wide intervention is written from the backend's own
 * `intervention_applied` event (chronicle.ts); other tools (a new citizen, an
 * owner's action, the clock) are recorded here, and their effects then
 * arrive as the backend's events like anything else.
 */
function land(
  text: string,
  command: Command | null,
  tool: DeterminedToolCall | null,
  live: boolean,
) {
  useDecrees.getState().land(tool ? toolMood(tool) : moodOf(command));
  if (live && (!tool || command)) return;
  const state = useWorld.getState().update?.state;
  useChronicle.getState().add({
    day: (state?.tick ?? 0) + 1,
    kind: "decree",
    text: tool
      ? describeTool(tool, state)
      : command
        ? describe(command, state)
        : `“${text}”`,
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
        thought:
          tool?.rationale ||
          (command
            ? reactionTo(command)
            : "Villagers repeat your words to one another, unsure what comes next."),
        source: tool ? "AI agent" : undefined,
      },
    ],
  });
}

/** What the player can change, by kind, with one example each (the backend's tools). */
const POWERS: { title: string; items: [string, string][] }[] = [
  {
    title: "The whole town",
    items: [
      ["Bread prices", "Make bread 20% cheaper"],
      ["Wages", "Set everyone's wages to 2 coins"],
      ["Money", "Give everyone 5 coins"],
      ["Hunger", "Throw a feast for the whole town"],
      ["Wheat", "A drought hits the fields"],
      ["Town policy", "Cap the bread price at 6 coins"],
    ],
  },
  {
    title: "Businesses",
    items: [
      ["A shop's price", "Hearth & Grain sells bread for 4 coins"],
      ["A shop's wage", "Elena's farm pays 2 coins a day"],
      ["Hiring", "Marcus hires Finn at the bakery"],
      ["Growth", "Upgrade Hearth & Grain"],
      ["Found a business", "Mira founds a bakery on plot 3"],
      ["Rent", "Set the rent on plot 5 to 4 coins"],
    ],
  },
  {
    title: "People and time",
    items: [
      ["A newcomer", "Spawn a blacksmith named Bob"],
      ["One villager", "Give Rowan 10 coins"],
      ["The clock", "Advance one day"],
      ["Playback", "Pause the simulation"],
    ],
  },
];

/**
 * An ⓘ beside the decree box: hover or focus it to see what can change.
 * Clicking an example puts it in the box.
 */
function PowersHint({ onPick }: { onPick: (example: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="god-hint"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="god-hint-button"
        aria-label="What can I change?"
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
      >
        <Info size={17} />
      </button>
      {open && (
        <div className="god-powers" role="tooltip">
          <strong>What you can change</strong>
          <p>
            Say it in your own words. Anything else gets an answer, and the
            world stays as it is.
          </p>
          <div className="god-powers-grid">
            {POWERS.map((group) => (
              <section key={group.title}>
                <h4>{group.title}</h4>
                {group.items.map(([label, example]) => (
                  <button
                    key={label}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      onPick(example);
                      setOpen(false);
                    }}
                  >
                    <span>{label}</span>
                    <em>“{example}”</em>
                  </button>
                ))}
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

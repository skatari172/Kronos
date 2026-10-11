/**
 * A conversation from the village, played back as a chat: the speaker's words
 * type themselves out, then their private reasoning, then how the listener
 * took it (their memory and feelings). Live, "Hear their side" asks the
 * listener's own agent for a reply (`POST /api/agents/{id}/ask`).
 */
import { useEffect, useState } from "react";
import {
  Lock,
  MessageCircle,
  RotateCcw,
  Sparkles,
  Volume2,
  X,
} from "lucide-react";
import { request } from "../api/client";
import { usePresentation, useWorld } from "../stores/world";
import { useMeetings, type Meeting, type TalkKind } from "../world/meetings";
import { otherSide } from "./chronicle";
import { useMusic } from "./music";
import { hush, speak } from "./voice";

const KIND_LABEL: Record<TalkKind, string> = {
  talk: "Conversation",
  friend: "A friendly word",
  gift: "A gift",
  deal: "A trade offer",
  loan: "A loan offer",
};

/** Characters typed per second. */
const TYPE_RATE = 42;

export function Conversation({ live }: { live: boolean }) {
  const meeting = useMeetings((s) => s.open);
  const show = useMeetings((s) => s.show);
  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === "Escape" && show(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [show]);
  if (!meeting) return null;
  return (
    <div className="convo-backdrop" onClick={() => show(null)}>
      <Chat key={meeting.id} meeting={meeting} live={live} />
    </div>
  );
}

/** Typewriter: how much of `text` is showing, from `start` (ms after mount). */
function useTyped(text: string, start: number, run: number) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0);
    let frame = 0;
    const began = performance.now() + start;
    const step = () => {
      const chars = Math.floor(
        ((performance.now() - began) / 1000) * TYPE_RATE,
      );
      setShown(Math.max(0, Math.min(text.length, chars)));
      if (chars < text.length) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [text, start, run]);
  return shown;
}

function Chat({ meeting, live }: { meeting: Meeting; live: boolean }) {
  const world = useWorld((s) => s.update?.state);
  const show = useMeetings((s) => s.show);
  const select = usePresentation((s) => s.select);
  const [run, setRun] = useState(0);
  const [reply, setReply] = useState<{ text: string; cited: number } | null>(
    null,
  );
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const name = (id: string) => world?.citizens[id]?.name ?? "Someone";
  const [a, b] = [name(meeting.a), name(meeting.b)];
  const talk = meeting.talk;
  const said = talk.line ?? `${a} ${talk.action}`;
  // Scripted offline chats never happened in the simulation: no reaction, no asking.
  const preview = talk.source === "Preview";
  const typed = useTyped(said, 650, run);
  const done = typed >= said.length;
  const typedReply = useTyped(reply?.text ?? "", 500, reply ? 1 : 0);
  // Who is speaking aloud right now (voice.ts): the speaker as their words
  // appear, the listener when their side is heard. Only real words are voiced.
  const [speaking, setSpeaking] = useState<"a" | "b" | null>(null);
  // Music stays well under the voices for as long as the chat is open.
  useEffect(() => {
    useMusic.getState().duck(true);
    return () => useMusic.getState().duck(false);
  }, []);
  useEffect(() => {
    if (!talk.line) return;
    let gone = false;
    // Ask for the voice the moment the chat opens; it lands as the words appear.
    const timer = setTimeout(() => {
      setSpeaking("a");
      void speak(meeting.a, talk.line!).then(
        () => !gone && setSpeaking((who) => (who === "a" ? null : who)),
      );
    }, 0);
    return () => {
      gone = true;
      clearTimeout(timer);
      hush();
    };
  }, [meeting.a, talk.line, run]);
  if (!world) return null;
  const reaction = otherSide(meeting.b, meeting.a, world, "Listener");

  async function hearSide() {
    setAsking(true);
    setError("");
    try {
      const question = talk.line
        ? `${a} just told you: "${talk.line}". What do you make of it, and how will you respond?`
        : `${a} ${talk.action}. What do you make of it, and how will you respond?`;
      const result = await request<{
        answer: string;
        cited_event_ids: string[];
      }>(
        `/api/agents/${meeting.b}/ask`,
        { question: question.slice(0, 300) },
        30_000,
      );
      setReply({ text: result.answer, cited: result.cited_event_ids.length });
      // The listener answers aloud, in their own voice.
      setSpeaking("b");
      void speak(meeting.b, result.answer).then(() =>
        setSpeaking((who) => (who === "b" ? null : who)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAsking(false);
    }
  }

  return (
    <div
      className={`convo ${talk.kind}`}
      role="dialog"
      aria-modal="true"
      aria-label={`${a} and ${b}`}
      onClick={(e) => e.stopPropagation()}
    >
      <header>
        <div className="convo-people">
          <Avatar id={meeting.a} name={a} />
          <MessageCircle size={16} aria-hidden />
          <Avatar id={meeting.b} name={b} />
        </div>
        <div className="convo-title">
          <strong>
            {a} &amp; {b}
          </strong>
          <small>
            {KIND_LABEL[talk.kind]} · Day {talk.day}
          </small>
        </div>
        <button
          className="panel-close"
          aria-label="Close"
          onClick={() => show(null)}
        >
          <X size={18} />
        </button>
      </header>

      <div className="convo-body">
        <div className="convo-row left">
          <span className="convo-who">
            {a}
            {speaking === "a" && <Volume2 size={13} className="speaking" />}
          </span>
          <div
            className={`convo-bubble ${talk.line ? "" : "action"} ${speaking === "a" ? "speaking" : ""}`}
          >
            {typed === 0 ? (
              <span className="typing" aria-label="typing">
                <i />
                <i />
                <i />
              </span>
            ) : (
              <>
                {said.slice(0, typed)}
                {!done && <span className="caret" />}
              </>
            )}
          </div>
        </div>

        {done && (
          <div className="convo-thought">
            <Lock size={13} aria-hidden />
            <div>
              <small>
                {a}&rsquo;s private reasoning
                {talk.source && <em className="chip">{talk.source}</em>}
              </small>
              <p>“{talk.reason}”</p>
            </div>
          </div>
        )}

        {done && !preview && (
          <div className="convo-row right">
            <span className="convo-who">{b}</span>
            <div className="convo-note">
              <small>
                How {b} feels about {a}
              </small>
              <p>{reaction.thought}</p>
            </div>
          </div>
        )}
        {done && preview && (
          <p className="panel-note">
            A scripted preview chat: no agents are running. Start the backend to
            see real conversations.
          </p>
        )}

        {reply && (
          <div className="convo-row right">
            <span className="convo-who">
              {b}
              {speaking === "b" && <Volume2 size={13} className="speaking" />}
            </span>
            <div
              className={`convo-bubble reply ${speaking === "b" ? "speaking" : ""}`}
            >
              {typedReply === 0 ? (
                <span className="typing">
                  <i />
                  <i />
                  <i />
                </span>
              ) : (
                reply.text.slice(0, typedReply)
              )}
              {typedReply >= reply.text.length && (
                <cite>
                  {b}&rsquo;s agent, from {reply.cited} event
                  {reply.cited === 1 ? "" : "s"} they remember
                </cite>
              )}
            </div>
          </div>
        )}
        {error && <p className="panel-note warn">{error}</p>}
      </div>

      <footer>
        {done && live && !preview && !reply && (
          <button
            className="convo-ask"
            disabled={asking}
            onClick={() => void hearSide()}
          >
            <Sparkles size={15} aria-hidden />
            {asking ? `${b} is thinking…` : `Hear ${b}’s side`}
          </button>
        )}
        <button
          className="convo-link"
          onClick={() => {
            setReply(null);
            setRun((n) => n + 1);
          }}
          title="Replay"
        >
          <RotateCcw size={14} aria-hidden /> Replay
        </button>
        <span className="convo-spacer" />
        {[meeting.a, meeting.b].map((id) => (
          <button
            key={id}
            className="convo-link"
            onClick={() => {
              select(id);
              show(null);
            }}
          >
            Open {name(id)}
          </button>
        ))}
      </footer>
    </div>
  );
}

const TINTS = [
  "#d9a35f",
  "#7fb6a8",
  "#c98aa8",
  "#8fae6a",
  "#a0a3d6",
  "#d48a6a",
];

function Avatar({ id, name }: { id: string; name: string }) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (
    <span
      className="convo-avatar"
      style={{ background: TINTS[h % TINTS.length] }}
    >
      {name.slice(0, 1)}
    </span>
  );
}

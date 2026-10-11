/**
 * Villagers speak their lines aloud, only when the player asks to hear a
 * conversation (Conversation.tsx). ElevenLabs voices through the backend
 * (`POST /api/voice`, the key stays on the server) when configured; otherwise
 * the browser's own speech, with a voice, pitch and pace of each villager's
 * own. The conversation window keeps the soundtrack low while it is open.
 */
import { API } from "../api/client";
import { hash } from "../world/assets";

let playing: HTMLAudioElement | null = null;
/** Once the backend says voices aren't configured, stop asking it. */
let serverVoices = true;

/** Stop whoever is speaking. */
export function hush() {
  playing?.pause();
  playing = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

/** Speak a villager's line; resolves when they finish (or are hushed). */
export async function speak(citizenId: string, text: string): Promise<void> {
  hush();
  const line = text.trim();
  if (!line) return;
  // The conversation window keeps the music low while it is open.
  if (serverVoices && (await fromServer(citizenId, line))) return;
  await fromBrowser(citizenId, line);
}

async function fromServer(citizenId: string, text: string) {
  try {
    const response = await fetch(`${API}/api/voice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ citizen_id: citizenId, text: text.slice(0, 600) }),
    });
    if (response.status === 503) serverVoices = false;
    if (!response.ok) return false;
    const url = URL.createObjectURL(await response.blob());
    const audio = new Audio(url);
    // Brisker than ElevenLabs' top speed, with the pitch kept natural.
    audio.playbackRate = 1.15;
    audio.preservesPitch = true;
    playing = audio;
    await new Promise<void>((done) => {
      audio.onended = audio.onpause = audio.onerror = () => done();
      void audio.play().catch(() => done());
    });
    URL.revokeObjectURL(url);
    return true;
  } catch {
    return false; // offline preview, or the backend is down
  }
}

function voices(): Promise<SpeechSynthesisVoice[]> {
  const list = window.speechSynthesis.getVoices();
  if (list.length) return Promise.resolve(list);
  return new Promise((resolve) => {
    const ready = () => resolve(window.speechSynthesis.getVoices());
    window.speechSynthesis.addEventListener("voiceschanged", ready, {
      once: true,
    });
    setTimeout(ready, 800);
  });
}

async function fromBrowser(citizenId: string, text: string) {
  if (!("speechSynthesis" in window)) return;
  const english = (await voices()).filter((v) => v.lang.startsWith("en"));
  const seed = hash(citizenId);
  const utterance = new SpeechSynthesisUtterance(text);
  if (english.length) utterance.voice = english[seed % english.length];
  // Each villager keeps their own pitch and pace.
  // Younger: pitch sits a little high, never low and gravelly.
  utterance.pitch = 1.0 + ((seed >>> 4) % 11) * 0.04;
  utterance.rate = 1.2 + ((seed >>> 9) % 7) * 0.025;
  await new Promise<void>((done) => {
    utterance.onend = utterance.onerror = () => done();
    window.speechSynthesis.speak(utterance);
  });
}

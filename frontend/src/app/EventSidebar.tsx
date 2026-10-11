/**
 * The chronicle as a live sidebar on the right: newest first, each event one
 * line with its icon and day. Hovering the list holds it still (new events
 * wait behind a "new" pill) so a line never moves while it's being read;
 * clicking one explains why it happened. "Full screen" opens the whole
 * chronicle page with search and filters.
 */
import { useState } from "react";
import { createPortal } from "react-dom";
import { BookOpen, ChevronsRight, Maximize2 } from "lucide-react";
import { usePresentation } from "../stores/world";
import { useChronicle, useChronicleView, type FeedItem } from "./feed";
import { WhyBox } from "./Header";
import { ICONS } from "./icons";

const SHOWN = 80;

export function EventSidebar() {
  const items = useChronicle((s) => s.items);
  const open = useChronicleView((s) => s.sidebar);
  const setOpen = useChronicleView((s) => s.setSidebar);
  const setFull = useChronicleView((s) => s.setFull);
  const select = usePresentation((s) => s.select);
  const [held, setHeld] = useState<FeedItem[] | null>(null);
  const [detail, setDetail] = useState<FeedItem | null>(null);
  const list = (held ?? items).slice(0, SHOWN);
  // While tucked away, the tab counts events newer than the last look.
  const newest = items[0]?.id ?? 0;
  const [seen, setSeen] = useState(newest);
  const unseen = Math.max(0, newest - seen);
  const waiting = held ? items.length - held.length : 0;

  if (!open)
    return (
      <button
        className="sidebar-tab"
        onClick={() => {
          setSeen(newest);
          setOpen(true);
        }}
        aria-label="Show the chronicle"
      >
        <BookOpen size={17} aria-hidden />
        <span>Chronicle</span>
        {unseen > 0 && (
          <span className="badge">{unseen > 99 ? "99+" : unseen}</span>
        )}
      </button>
    );

  return (
    <aside className="event-sidebar" aria-label="Chronicle">
      <header>
        <div>
          <h2>Chronicle</h2>
          <small>
            <i className="live-dot" /> What the villagers are doing
          </small>
        </div>
        <button
          className="sidebar-icon"
          title="Hide"
          aria-label="Hide the chronicle"
          onClick={() => {
            setSeen(newest);
            setOpen(false);
          }}
        >
          <ChevronsRight size={17} />
        </button>
      </header>
      {waiting > 0 && (
        <button className="sidebar-new" onClick={() => setHeld(null)}>
          {waiting} new event{waiting === 1 ? "" : "s"} ↑
        </button>
      )}
      <ol
        onMouseEnter={() => setHeld(items)}
        onMouseLeave={() => !detail && setHeld(null)}
      >
        {list.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <li key={item.id} className={item.kind}>
              <button
                onClick={() => {
                  setHeld((h) => h ?? items);
                  setDetail(item);
                }}
              >
                <span className="sidebar-icon-dot">
                  <Icon size={15} aria-hidden />
                </span>
                <span className="sidebar-text">{item.text}</span>
                <small>Day {item.day}</small>
              </button>
            </li>
          );
        })}
        {!list.length && (
          <li className="sidebar-empty">Waiting for the first events…</li>
        )}
      </ol>
      <button className="sidebar-full" onClick={() => setFull(true)}>
        <Maximize2 size={14} aria-hidden /> See full screen
      </button>
      {detail &&
        // In <body>, so the sidebar's blur can't trap the full-screen box.
        createPortal(
          <WhyBox
            event={detail}
            onClose={() => {
              setDetail(null);
              setHeld(null);
            }}
            onPerson={(id) => {
              select(id);
              setDetail(null);
              setHeld(null);
            }}
          />,
          document.body,
        )}
    </aside>
  );
}

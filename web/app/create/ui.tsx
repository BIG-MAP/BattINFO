"use client";

// How a row looks. Nothing in this file knows what a schema or a record is --
// it is handed a label, a control and some state, and lays them out; the look
// is tree.module.css.
//
// A value is one ValueRow, whatever names it -- a field, an index, a map key, or
// a selector: name | control, removable; what the validator says under the
// control. A section is one Branch, whatever it holds -- an object, a list or a
// map. Each shape is defined once.

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import styles from "./tree.module.css";

/** Around the whole tree: what its colours and its narrow layout go by. */
export const TREE = styles.tree;
export const INPUT = styles.input;
export const INPUT_FLAGGED = styles.inputFlagged;
export const CHOICE = styles.choice;
export const HINT = styles.hint;

/** How many levels of open sections stay pinned while their rows scroll. A
 *  fourth costs more of the viewport than the orientation is worth. */
const PINNED_LEVELS = 3;

/** Something just added: brought into view and its first box focused, so it
 *  need not be looked for. Once, as it first shows. */
function useArrival(ref: RefObject<HTMLElement>, fresh?: boolean) {
  useEffect(() => {
    if (!fresh || !ref.current) return;
    ref.current.scrollIntoView({ block: "center", behavior: "smooth" });
    ref.current.querySelector<HTMLElement>("input, select, textarea")?.focus({ preventScroll: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Rotates when its own <details> opens, so one glyph shows both states. */
function Chevron() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden className={styles.chevron}>
      <path d="M4.5 2.5l3.5 3.5-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// The schema's description, one hover away, beside the control it describes:
// the question is always "what do I put in this box". An icon, because one
// printed description per field drowns the fields it explains. Focusable, and
// the same sentence rides on `title` for a screen reader.
function Info({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <span
      tabIndex={0}
      title={text}
      className="group/info relative w-3.5 shrink-0 cursor-help text-ink-faint/30 outline-none transition-colors group-hover/row:text-ink-faint/70 hover:!text-ink-faint focus-visible:!text-ink-faint"
    >
      <svg viewBox="0 0 16 16" aria-hidden className="w-3.5">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <path
          d="M6.1 6.1a1.9 1.9 0 1 1 2.5 1.8c-.4.15-.6.5-.6.9v.3"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
        <circle cx="8" cy="11.6" r="0.75" fill="currentColor" />
      </svg>
      <span
        aria-hidden
        className="pointer-events-none absolute left-5 top-0 z-[35] hidden w-[min(20rem,70vw)] rounded border border-border bg-raised p-2 text-xs font-normal normal-case leading-snug text-ink shadow-lg group-hover/info:block group-focus/info:block"
      >
        {text}
      </span>
    </span>
  );
}

function Remove({ onClick }: { onClick?: () => void }) {
  if (!onClick) return null;
  return (
    <button type="button" onClick={onClick} aria-label="Remove" title="Remove" className={styles.remove}>
      ×
    </button>
  );
}

export function ValueRow({
  label,
  help,
  onRemove,
  wanted,
  problem,
  fresh,
  children,
}: {
  label: React.ReactNode;
  help?: string;
  onRemove?: () => void;
  wanted?: boolean;
  problem?: string;
  /** Just added: brought into view and marked for a moment. */
  fresh?: boolean;
  children: React.ReactNode;
}) {
  const row = useRef<HTMLDivElement>(null);
  useArrival(row, fresh);
  return (
    <div
      ref={row}
      className={`group/row ${styles.row} ${wanted || problem ? styles.flagged : ""} ${fresh ? styles.fresh : ""}`}
    >
      <span className={styles.label}>{label}</span>
      <div className={styles.control}>
        <Info text={help} />
        {children}
        <Remove onClick={onRemove} />
      </div>
      {wanted || problem ? <p className={styles.problem}>{problem ?? "required"}</p> : null}
    </div>
  );
}

// A section starts shut unless the caller asks otherwise, and the initial
// state is frozen at mount so a later re-render never yanks one closed under
// the reader. Its ground is a faint tint deeper per level.
export function Branch({
  title,
  help,
  note,
  problems,
  startOpen,
  fresh,
  level,
  onRemove,
  children,
}: {
  title: React.ReactNode;
  help?: string;
  note?: string;
  /** Whether something is wrong in it, said while it is shut. */
  problems?: boolean;
  startOpen?: boolean;
  /** Just added: opened, brought into view and marked for a moment. */
  fresh?: boolean;
  /** How many sections enclose this one: its tint, and where it pins. */
  level: number;
  onRemove?: () => void;
  children: React.ReactNode;
}) {
  const [initiallyOpen] = useState(!!(startOpen || fresh));
  const section = useRef<HTMLDetailsElement>(null);
  useArrival(section, fresh);
  const pinned = level < PINNED_LEVELS;
  const depth = { "--depth": level, ...(pinned ? { "--level": level } : {}) } as React.CSSProperties;
  return (
    <details
      ref={section}
      open={initiallyOpen}
      className={`${styles.branch} ${fresh ? styles.fresh : ""}`}
      style={depth}
    >
      <summary className={`group/row ${styles.head} ${pinned ? styles.pinned : ""}`}>
        <Chevron />
        <span className={styles.title}>{title}</span>
        <Info text={help} />
        {note ? <span className={styles.note}>{note}</span> : null}
        {problems ? <span className={styles.toFix}>to fix</span> : null}
        {/* right after what it removes, not off at the far edge */}
        <Remove onClick={onRemove} />
      </summary>
      <div className={styles.nested}>{children}</div>
    </details>
  );
}

/** The last thing in a list: one more item. */
export function AddItem({ to, onClick }: { to: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={styles.addItem}>
      + New item in {to}
    </button>
  );
}

/** One entry in the picker. Structural, so a schema Field satisfies it without
 *  this file importing anything about schemas. */
export interface Addable {
  key: string;
  label: string;
  help?: string;
}

// What may be added to `to`: a button, and over the form the choices, filtered
// as typed, each with what it is; the first, or the one picked with the arrows,
// taken on Enter; Escape, the ×, the button again or a click elsewhere closing
// them. Everything the schema allows here and nothing else, which is what keeps
// a record legal by construction. Where the names are the author's (a map's),
// one typed that `fits` is offered as well.
export function AddMenu({
  to,
  options,
  onAdd,
  fits,
}: {
  to: string;
  options: Addable[];
  onAdd: (key: string) => void;
  fits?: (name: string) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  // Opens upwards when there is no room below it.
  useLayoutEffect(() => {
    const el = panel.current;
    if (!open || !el) return;
    const box = el.getBoundingClientRect();
    el.classList.toggle(styles.above, box.bottom > window.innerHeight - 8 && box.top > box.height);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const press = (e: PointerEvent) => root.current?.contains(e.target as Node) || close();
    const key = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("pointerdown", press);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", press);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  if (!options.length && !fits) return null;

  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = options.filter((o) => words.every((w) => `${o.label} ${o.key} ${o.help ?? ""}`.toLowerCase().includes(w)));
  const typed = filter.trim();
  const own = fits && typed && !options.some((o) => o.key === typed) && fits(typed) ? typed : undefined;
  const choices = [...shown.map((o) => o.key), ...(own ? [own] : [])];
  const pick = (key: string) => {
    onAdd(key);
    setOpen(false);
    setFilter("");
    setActive(0);
  };

  return (
    <div className={styles.add} ref={root}>
      <button
        type="button"
        className={styles.addHead}
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen(!open)}
      >
        + Add to {to}
      </button>
      {open ? (
        <div className={styles.addPanel} ref={panel}>
          <div className={styles.addFilter}>
            <input
              autoFocus
              placeholder={fits ? "Type a name or select one" : `Search ${options.length} fields`}
              aria-label={`What to add to ${to}`}
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setActive(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, choices.length - 1));
                else if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
                else if (e.key === "Enter" && choices[active]) pick(choices[active]);
                else return;
                e.preventDefault();
              }}
            />
            <button type="button" className={styles.close} onClick={() => setOpen(false)} aria-label="Close" title="Close">
              ×
            </button>
          </div>
          <div className={styles.options} role="listbox">
            {shown.map((option, i) => (
              <button
                key={option.key}
                type="button"
                role="option"
                aria-selected={i === active}
                className={styles.option}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(option.key)}
              >
                <span className={styles.optionLabel}>{option.label}</span>
                {option.help ? <span className={styles.optionHelp}>{option.help}</span> : null}
              </button>
            ))}
            {own ? (
              <button
                type="button"
                role="option"
                aria-selected={active === shown.length}
                className={styles.option}
                onMouseEnter={() => setActive(shown.length)}
                onClick={() => pick(own)}
              >
                <span className={styles.optionLabel}>+ Add “{own}”</span>
              </button>
            ) : null}
            {choices.length ? null : <p className={styles.noOption}>{fits ? "Type a name to add it" : "No matches"}</p>}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// The page is beta because the contract it draws itself from is: the schemas
// may still be renamed or extended before battinfo 1.0. Said once, here, and
// shown on both views -- the site already carries a full-bleed prototype
// banner, and a second one under it reads as shouting rather than as a note.
// A badge inside the page, not a bar across the top of it: the site already
// shows a full-bleed prototype banner above every page, and a second one under
// it reads as shouting rather than as the note it is.
export function BetaBadge({ className = "" }: { className?: string }) {
  return (
    <span
      title="Records written now stay readable, but a field may be renamed or added under them before battinfo 1.0."
      className={`shrink-0 rounded-full border border-warning/30 bg-warning-tint px-2.5 py-1 text-xs font-medium text-warning ${className}`}
    >
      beta · schemas may change until battinfo 1.0
    </span>
  );
}

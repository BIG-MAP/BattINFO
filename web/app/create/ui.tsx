"use client";

// How a row looks. Nothing in this file knows what a schema or a record is --
// it is handed a label, a control and some state, and lays them out.
//
// Layout rule: the row is the unit, and its slots never move --
//   structure (chevron or +) | label | remove | info | control | state
// The label names the row and the right-hand side carries everything about the
// value: the control, whether it is still wanted, and what the validator says
// about it. Nesting indents the label only; the control column shrinks to fit,
// so controls line up on one right edge at any depth. Every row that holds a
// value is one ValueRow, whatever names it -- a field, an index, a map key, or
// a selector -- so the shape is defined once.

import { useState } from "react";
import styles from "./tree.module.css";

const ROW_BASE = "group/row flex items-center gap-1.5 py-1.5 pr-1";
const NAME = "min-w-0 max-w-[14rem] truncate text-sm";
const SMALL = "text-[10px] uppercase tracking-wide";

export const DIVIDED = "border-b border-ink-faint/10";
export const LEAF_ROW = `${ROW_BASE} hover:bg-ink/[0.03]`;
export const CONTROL = "w-[16rem] min-w-[7rem]";
export const LABEL = `${NAME} text-ink-faint`;
export const TITLE = `${NAME} font-medium text-ink`;
export const INPUT =
  "w-full rounded border bg-surface/60 px-2 py-1 text-sm text-ink focus:border-brand-500 focus:bg-surface focus:outline-none";

const HEAD_ROW = `${ROW_BASE} ${DIVIDED} rounded-sm pl-2 hover:bg-ink/[0.04]`;

// An open section pins itself while its contents scroll past, each level
// parking below the one above it, so the way down into a record stays on
// screen. The anchor is the bottom of the toolbar -- the site header (4rem)
// and the toolbar (3.3rem) are both sticky above -- and each level is one
// summary row (33px) further down.
//
// Only three levels deep: a fourth costs more of the viewport than the
// orientation is worth, and the outermost headings are the ones that say
// where you are. Deeper sections scroll away like any other row.
const PINNED_LEVELS = 3;
const TOOLBAR_BOTTOM = "7.3rem";
const HEAD_HEIGHT = 2.0625;
const STATE = `w-16 shrink-0 pl-1.5 leading-tight ${SMALL}`;
const TAG = `shrink-0 text-warning ${SMALL}`;

// Own-state styling lives in tree.module.css: Tailwind cannot scope a rule to
// the element's own <details>, which nested chevrons and tags need.

/** Rotates when its own <details> opens, so one glyph shows both states. */
export function Chevron({ hidden }: { hidden?: boolean }) {
  if (hidden) return <span className="w-3 shrink-0" />;
  return (
    <svg viewBox="0 0 12 12" aria-hidden className={`w-3 shrink-0 ${styles.chevron}`}>
      <path d="M4.5 2.5l3.5 3.5-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// The schema's description, one hover away, and sitting beside the control it
// describes rather than beside the label: the question is always "what do I put
// in this box". Kept to an icon because one printed description per field
// drowns the fields it explains. Focusable, and the same sentence rides on
// `title`, so it survives for a screen reader and for anyone the hover panel
// never reaches.
export function Info({ text }: { text?: string }) {
  if (!text) return <span className="w-3.5 shrink-0" />;
  return (
    <span
      tabIndex={0}
      title={text}
      className="group/info relative w-3.5 shrink-0 cursor-help text-ink-faint/20 outline-none transition-colors group-hover/row:text-ink-faint/60 hover:!text-ink-faint focus-visible:!text-ink-faint"
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
        className="pointer-events-none absolute right-5 top-0 z-20 hidden w-80 rounded border border-border bg-surface p-2 text-xs leading-snug text-ink shadow-lg group-hover/info:block group-focus/info:block"
      >
        {text}
      </span>
    </span>
  );
}

/** The validator's complaint, under the control it is about rather than under
 *  the label, so what is said sits with the thing it is said about. */
function UnderControl({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <div className="flex pb-1 pr-1">
      <span className="flex-1" />
      <div className={`${CONTROL} text-[11px] leading-snug text-warning`}>{text}</div>
      <span className="w-16 shrink-0" />
    </div>
  );
}

/** Always visible and big enough to hit. Rows that cannot be removed reserve
 *  the same slot so nothing shifts. */
export function Remove({ onClick }: { onClick?: () => void }) {
  if (!onClick) return <span className="w-6 shrink-0" />;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Remove"
      title="Remove"
      className="h-6 w-6 shrink-0 rounded text-base leading-none text-ink-faint/50 hover:bg-error/10 hover:text-error"
    >
      ×
    </button>
  );
}

export function Label({ text }: { text: string }) {
  return (
    <span className={LABEL} title={text}>
      {text}
    </span>
  );
}

/** Every row that carries a value, whatever names it on the left. Keeping the
 *  one shape here is what stops a change to rows having to be made four times. */
export function ValueRow({
  label,
  help,
  onRemove,
  wanted,
  problem,
  children,
}: {
  label: React.ReactNode;
  help?: string;
  onRemove?: () => void;
  wanted?: boolean;
  problem?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={DIVIDED}>
      <div className={LEAF_ROW}>
        <Chevron hidden />
        {label}
        <Remove onClick={onRemove} />
        <span className="flex-1" />
        <Info text={help} />
        <div className={CONTROL}>{children}</div>
        {/* The slot is always there so nothing shifts, but the word only exists
            when it is true: hiding it with `text-transparent` left every row
            announcing "required" to a screen reader. */}
        <span className={`${STATE} text-warning`}>{wanted ? "required" : null}</span>
      </div>
      <UnderControl text={problem} />
    </div>
  );
}

function Nested({ children }: { children: React.ReactNode }) {
  return <div className="ml-[7px] border-l border-ink-faint/15 pl-5">{children}</div>;
}

// A collapsible row with children under it: objects, arrays and maps differ
// only in what they hold, so all three use this. Tinted and undivided, so it
// reads as a heading over the rows it contains. Its mark stays on the left,
// because it describes what opening the section would reveal rather than a
// value.
//
// A section starts shut unless the caller asks otherwise, and the initial
// state is frozen at mount so a later re-render never yanks one closed under
// the reader.
export function Branch({
  title,
  help,
  note,
  problems,
  startOpen,
  level,
  onRemove,
  children,
}: {
  title: React.ReactNode;
  help?: string;
  note?: string;
  problems?: boolean;
  startOpen?: boolean;
  /** How many sections enclose this one, which is where it parks when open. */
  level?: number;
  onRemove?: () => void;
  children: React.ReactNode;
}) {
  const [initiallyOpen] = useState(!!startOpen);
  // Where it parks is this component's business; whether it parks at all is
  // the stylesheet's, which can see the section's own open state.
  const pinned = level !== undefined && level < PINNED_LEVELS;
  const park = {
    "--pin-top": `calc(${TOOLBAR_BOTTOM} + ${(level ?? 0) * HEAD_HEIGHT}rem)`,
    "--pin-z": PINNED_LEVELS - (level ?? 0),
  } as React.CSSProperties;
  return (
    <details open={initiallyOpen} className="mt-3 first:mt-0">
      <summary
        className={`${HEAD_ROW} ${styles.headWhenOpen} ${pinned ? styles.pinWhenOpen : ""} cursor-pointer list-none marker:hidden`}
        style={pinned ? park : undefined}
      >
        <Chevron />
        <span className={TITLE}>{title}</span>
        <Info text={help} />
        <Remove onClick={onRemove} />
        {problems ? <span className={`${TAG} ${styles.hideWhenOpen}`}>to fix</span> : null}
        <span className="flex-1" />
        <span className={`${CONTROL} text-xs text-ink-faint/50`}>{note}</span>
        <span className="w-16 shrink-0" />
      </summary>
      <Nested>{children}</Nested>
    </details>
  );
}

/** One entry in the picker. Structural, so a schema Field satisfies it without
 *  this file importing anything about schemas. */
export interface Addable {
  key: string;
  label: string;
  help?: string;
}

// The picker: everything allowed here that is not present yet. Nothing else can
// be offered, which is what keeps a record legal by construction. Open, it is
// visibly its own zone -- tinted, behind a brand rail -- so a list of things
// that could exist is never read as a list of things that do. It closes on
// choosing, because the chosen one is now a row below it.
export function AddField<T extends Addable>({
  options,
  onAdd,
}: {
  options: T[];
  onAdd: (option: T) => void;
}) {
  const [open, setOpen] = useState(false);
  if (options.length === 0) return null;

  return (
    <details open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary
        className={`${ROW_BASE} cursor-pointer list-none rounded-sm text-brandtext marker:hidden hover:bg-ink/[0.03] ${styles.tintWhenOpen}`}
      >
        <Chevron />
        <span className="text-sm">
          add <span className="text-ink-faint/60">({options.length})</span>
        </span>
        <span className="flex-1" />
      </summary>
      <div className="mb-2 ml-[7px] max-h-72 overflow-y-auto border-l-2 border-brand-500/40 bg-brand-500/[0.04] pl-5">
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => {
              onAdd(option);
              setOpen(false);
            }}
            className={`${ROW_BASE} ${DIVIDED} w-full text-left last:border-0 hover:bg-brand-500/10`}
          >
            <span className="w-3 shrink-0 text-center text-sm text-brandtext">+</span>
            <span className={`${LABEL} text-ink`} title={option.label}>
              {option.label}
            </span>
            <span className="flex-1" />
            <span className={`${CONTROL} truncate text-xs text-ink-faint/60`}>{option.help}</span>
          </button>
        ))}
      </div>
    </details>
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

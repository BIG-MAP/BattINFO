"use client";

// Which input a value gets. One question, answered from the schema's control
// kind and nothing else -- the tree decides what to render where, this decides
// what it looks like to type into.

import { useState } from "react";
import { controlFor, type Field } from "./schema";
import { INPUT } from "./ui";
import { SUGGESTS } from "./vocab";

// A schema `format` names a closed shape the browser already knows how to
// collect, so the control becomes the right one instead of a bare text box.
// `date-time` is deliberately absent: the native picker yields
// "2026-09-17T10:30" with no offset, which the format then rejects -- a worse
// box than a plain one.
const INPUT_TYPE: Record<string, string> = { uri: "url", email: "email", date: "date" };

// The record holds a number; the box holds what was typed. They diverge only
// while a decimal is half-written -- "0.0" on the way to "0.05" is already a
// whole number whose own text is "0", so echoing the record back would eat the
// digit under the cursor and put 0.05 out of reach. The typed text therefore
// wins for as long as it still parses to the value this box emitted; a value
// from anywhere else (a template, an upload, a reset) does not parse back and
// takes over.
function NumberInput({
  value,
  onChange,
  className,
  label,
}: {
  value: unknown;
  onChange: (next: unknown) => void;
  className: string;
  label: string;
}) {
  const [typed, setTyped] = useState(value === undefined ? "" : String(value));
  const mine = typed.trim() !== "" && Number(typed) === value;
  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      className={className}
      value={mine ? typed : value === undefined ? "" : String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        setTyped(raw);
        // Keep what was typed when it is not a number yet. Storing NaN would be
        // a lie; the raw string lets the validator say "expected a number".
        const parsed = Number(raw);
        onChange(raw.trim() !== "" && Number.isFinite(parsed) ? parsed : raw);
      }}
    />
  );
}

export function Leaf({
  field,
  value,
  onChange,
  flagged,
}: {
  field: Field;
  value: unknown;
  onChange: (next: unknown) => void;
  flagged?: boolean;
}) {
  const control = controlFor(field.loc);
  const cls = `${INPUT} ${flagged ? "border-warning/60" : "border-border"}`;

  switch (control.kind) {
    case "select":
      return (
        <select
          aria-label={field.label}
          className={cls}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">—</option>
          {control.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );

    case "boolean":
      return (
        <input
          type="checkbox"
          aria-label={field.label}
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-border bg-surface"
        />
      );

    case "number":
      return <NumberInput value={value} onChange={onChange} className={cls} label={field.label} />;

    // A value the author does not own: the schema permits any shape here, so
    // no control could edit it without changing it. Shown whole, carried
    // whole. The schema's own description -- one hover away -- says why
    // ("never authored by hand", "ignored by the publish pipeline").
    case "opaque":
      return (
        <div
          role="group"
          aria-label={`${field.label}, carried unchanged`}
          className="max-h-24 overflow-auto rounded border border-dashed border-border bg-ink/[0.03] px-2 py-1 font-mono text-[11px] leading-snug text-ink-faint"
        >
          {JSON.stringify(value)}
        </div>
      );

    default:
      return (
        <input
          type={control.kind === "text" ? (INPUT_TYPE[control.format ?? ""] ?? "text") : "text"}
          list={SUGGESTS[field.key]}
          aria-label={field.label}
          className={cls}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}

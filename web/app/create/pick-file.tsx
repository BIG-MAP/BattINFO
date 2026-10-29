"use client";

// The blocks both screens begin with. A dashed border is the usual sign for
// "put a file here", so the file panel keeps it and the others do not -- they
// are different kinds of action and should not be made to look alike.

import { useRef } from "react";
import Link from "next/link";

const PANEL = "rounded-lg border px-5 py-4";
const BUTTON =
  "shrink-0 rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:border-brand-500";

function Row({ title, note, children }: { title: string; note: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <p className="mt-1 text-sm text-ink-muted">{note}</p>
      </div>
      {children}
    </div>
  );
}

export function ActionPanel({
  title,
  note,
  action,
  onAction,
}: {
  title: string;
  note: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <section className={`${PANEL} border-border bg-surface`}>
      <Row title={title} note={note}>
        <button type="button" onClick={onAction} className={BUTTON}>
          {action}
        </button>
      </Row>
    </section>
  );
}

export function FilePanel({
  note,
  onChoose,
  error,
}: {
  note: string;
  onChoose: (file: File) => void;
  error?: string | null;
}) {
  const pick = useRef<HTMLInputElement>(null!);
  return (
    <section className={`${PANEL} border-dashed border-border bg-ink/[0.02]`}>
      <Row title="Open a file" note={note}>
        <button type="button" onClick={() => pick.current?.click()} className={BUTTON}>
          Choose file
        </button>
      </Row>
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
      <input
        ref={pick}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = ""; // so the same file can be picked twice
          if (file) onChoose(file);
        }}
      />
    </section>
  );
}

/** Back to the step before, labelled with where it goes. `onNavigate` may
 *  call preventDefault to keep the reader here. */
export function BackLink({
  href,
  onNavigate,
  children,
}: {
  href: string;
  onNavigate?: (event: React.MouseEvent) => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className="inline-flex items-center gap-1.5 text-sm text-ink-faint hover:text-ink"
    >
      <svg viewBox="0 0 12 12" aria-hidden className="w-3">
        <path d="M7.5 2.5L4 6l3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {children}
    </Link>
  );
}

"use client";

// Step two: the type is settled, so the question is what the record starts
// from. Asked on its own, with no form behind it -- a blank form under a
// question is a form you read past, and it reports every required field as
// missing before anyone has written a thing.
//
// Three answers, three blocks. Opening a file and starting blank are one line
// each; templates are a list, so they get a block of their own rather than
// being folded in beside two buttons.

import { useState } from "react";
import { asTemplate, read, type Loaded } from "./load";
import { ActionPanel, FilePanel } from "./pick-file";
import type { RecordType } from "./types";
import { blankFor } from "./schema";
import { TEMPLATES } from "@/lib/templates.generated";
import { detectRecordType } from "@/lib/validate";

type Obj = Record<string, unknown>;

export function HowToStart({ type, onBegin }: { type: RecordType; onBegin: (begun: Loaded) => void }) {
  const [error, setError] = useState<string | null>(null);
  const templates = TEMPLATES.filter((t) => detectRecordType(t.record as Obj) === type.key);
  const what = type.label.toLowerCase();

  async function openFile(file: File) {
    setError(null);
    try {
      onBegin(await read(file, type));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  }

  return (
    <div className="mt-8 space-y-3">
      <FilePanel
        note={`Open a ${what} saved earlier. Unrecognised fields are dropped.`}
        onChoose={openFile}
        error={error}
      />

      <ActionPanel
        title="Blank"
        note="Start with the required fields only."
        action="Start"
        onAction={() => onBegin({ record: blankFor(type.root) as Obj, removed: [] })}
      />

      {templates.length ? (
        <section className="rounded-lg border border-border bg-surface px-5 py-4">
          <h3 className="text-sm font-semibold text-ink">Templates</h3>
          <p className="mt-1 text-sm text-ink-muted">Reviewed records, roughly one per cell format.</p>
          <div className="mt-3 overflow-hidden rounded border border-border">
            {templates.map((template) => (
              <button
                key={template.slug}
                type="button"
                onClick={() =>
                  onBegin({ record: asTemplate(structuredClone(template.record) as Obj, type), removed: [] })
                }
                className="flex w-full items-baseline justify-between gap-4 border-b border-border/50 px-4 py-2 text-left last:border-0 hover:bg-brand-500/10"
              >
                <span className="truncate text-sm text-ink">{template.slug}</span>
                <span className="shrink-0 text-xs text-ink-faint">{template.format}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

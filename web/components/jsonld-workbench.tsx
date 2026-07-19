"use client";

// The "JSON-LD document" mode of /validate: view a published document a few
// different ways and run three independent browser-side checks on it. Heavy
// work (the jsonld library) is imported on demand so the page stays light until
// you press Run.

import { useRef, useState } from "react";
import {
  runJsonLdLayers,
  effectiveContext,
  extractSummary,
  type JsonLdLib,
  type LayeredIssue,
  type WorkbenchOutput,
} from "@/lib/jsonld-workbench";
import {
  validateRecord,
  validateRecordAs,
  detectRecordType,
  DISCRIMINATORS,
  type Issue,
  type ValidationResult,
} from "@/lib/validate";
import { jsonldGallery } from "@/lib/jsonld.generated";
import { JsonLdTree } from "@/components/jsonld-tree";
import { SummaryView, TableView, JsonView } from "@/components/jsonld-views";

const LAYER_LABEL: Record<string, string> = {
  "well-formedness": "well-formedness",
  structural: "structural",
  semantic: "semantic",
};

type ViewKind = "summary" | "table" | "tree" | "json";

const VIEWS: { key: ViewKind; label: string; hint: string }[] = [
  { key: "summary", label: "Summary", hint: "A datasheet: identity, properties, and components at a glance." },
  { key: "table", label: "Table", hint: "The same facts as plain tables you can scan or copy." },
  { key: "tree", label: "Tree", hint: "The full document as a collapsible tree, term by term." },
  { key: "json", label: "JSON", hint: "The document as formatted text." },
];

function IssueRow({ issue }: { issue: LayeredIssue }) {
  const isError = issue.severity === "error";
  return (
    <li className="flex items-start gap-2 rounded-lg border border-border bg-white p-3">
      <span className="mt-0.5 rounded bg-tint px-1.5 py-0.5 font-mono text-[10px] font-semibold text-brand-700">
        {LAYER_LABEL[issue.layer]}
      </span>
      <span
        className={`mt-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
          isError ? "bg-error-tint text-error" : "bg-warning-tint text-warning"
        }`}
      >
        {issue.severity}
      </span>
      <div>
        <p className="font-mono text-xs text-ink-faint">{issue.path}</p>
        <p className="text-sm text-ink">{issue.message}</p>
      </div>
    </li>
  );
}

function LayerSection({ title, note, issues }: { title: string; note: string; issues: LayeredIssue[] }) {
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.filter((i) => i.severity === "warning").length;
  const clean = issues.length === 0;
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <span className={`text-xs ${clean ? "text-volt-700" : "text-ink-muted"}`}>
          {clean ? "no issues" : `${errors} error${errors === 1 ? "" : "s"} · ${warnings} warning${warnings === 1 ? "" : "s"}`}
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-faint">{note}</p>
      {issues.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {issues.map((issue, i) => (
            <IssueRow key={i} issue={issue} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// The structural layer reuses the canonical Ajv schemas from lib/validate. For
// a canonical record it is the full structural verdict; for a published JSON-LD
// document, lib/validate returns a pointer (schema validates the record form),
// which we relay honestly.
function structuralIssues(result: ValidationResult): LayeredIssue[] {
  return result.issues.map((i: Issue) => ({ ...i, layer: "structural" as const }));
}

function stripContext(doc: Record<string, unknown>): Record<string, unknown> {
  const { ["@context"]: _drop, ...rest } = doc;
  void _drop;
  return rest;
}

export default function JsonLdWorkbench() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState<WorkbenchOutput | null>(null);
  const [structural, setStructural] = useState<ValidationResult | null>(null);
  const [override, setOverride] = useState("auto");
  const [view, setView] = useState<ViewKind>("summary");
  const [form, setForm] = useState<"canonical" | "raw">("canonical");
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function run(next?: string, forced = override) {
    const text = next ?? input;
    if (next !== undefined) setInput(next);
    if (!text.trim()) return;
    setBusy(true);
    try {
      const mod = await import("jsonld");
      const jsonld = ((mod as { default?: unknown }).default ?? mod) as JsonLdLib;
      const out = await runJsonLdLayers(text, jsonld);
      setOutput(out);
      setStructural(forced === "auto" ? validateRecord(text) : validateRecordAs(text, forced));
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    await run(await file.text());
  }

  function onOverride(value: string) {
    setOverride(value);
    if (input.trim()) void run(undefined, value);
  }

  const detected = output?.parsed ? detectRecordType(output.parsed) : null;
  const structuralNote =
    override !== "auto"
      ? `Forced record type: ${override}. This is a browser pre-check; the CLI is the canonical verdict.`
      : detected
        ? `Canonical record detected (${detected}) — validated against the same JSON Schema battinfo validate uses. Browser pre-check.`
        : "Structural JSON Schema describes the canonical record form. Pick a type to force-check, or validate the record on the Record tab.";

  const summary = output?.framed ? extractSummary(output.framed) : null;
  const showForm = view === "tree" || view === "json";

  return (
    <div>
      {/* Input */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">JSON-LD document</h2>
        <div className="flex flex-wrap gap-3 text-xs font-medium">
          <ExamplePicker onPick={(doc) => run(doc)} />
          <button onClick={() => fileInput.current?.click()} className="text-brand-600 hover:text-brand-700">
            Open a file…
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".json,.jsonld,application/json,application/ld+json"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </div>
      </div>
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onDrop={(e) => {
          e.preventDefault();
          void onFile(e.dataTransfer.files?.[0]);
        }}
        onDragOver={(e) => e.preventDefault()}
        spellCheck={false}
        placeholder="Paste or drop a JSON-LD document, or load an example above."
        className="h-72 w-full resize-y rounded-xl border border-border bg-ink-deep p-4 font-mono text-sm text-paper placeholder:text-ink-faint focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
      />
      <button
        onClick={() => run()}
        disabled={busy}
        className="mt-4 w-full rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:opacity-60"
      >
        {busy ? "Working…" : "View and check"}
      </button>

      {/* Viewer */}
      <div className="mt-10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex flex-wrap rounded-lg border border-border p-1">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => setView(v.key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  view === v.key ? "bg-tint text-brand-700" : "text-ink-muted hover:text-ink"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
          {showForm ? (
            <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
              {(["canonical", "raw"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setForm(f)}
                  className={`rounded-md px-2.5 py-1 font-medium transition ${
                    form === f ? "bg-tint text-brand-700" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {f === "canonical" ? "Canonical" : "Raw"}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <p className="mb-3 mt-2 text-xs text-ink-faint">{VIEWS.find((v) => v.key === view)?.hint}</p>

        {!output ? (
          <div className="flex h-72 items-center justify-center rounded-xl border border-dashed border-border bg-surface text-sm text-ink-faint">
            Load a document to view it.
          </div>
        ) : (
          <ViewBody view={view} form={form} output={output} summary={summary} />
        )}
      </div>

      {/* Checks */}
      {output ? (
        <div className="mt-10 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Checks</h2>
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              Validate as
              <select
                value={override}
                onChange={(e) => onOverride(e.target.value)}
                className="rounded-md border border-border bg-white px-2 py-1 font-mono text-xs text-ink"
              >
                <option value="auto">auto-detect</option>
                {Object.keys(DISCRIMINATORS).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-ink-muted">
            Three independent layers, each reporting on its own. This is a browser pre-check — the{" "}
            <code className="text-xs">battinfo</code> package (or the publish gate) remains the canonical verdict, and
            runs the referential-integrity and shape checks that need your full record set.
          </p>
          <LayerSection
            title="Layer 1 — JSON-LD well-formedness"
            note="Parses, resolves a @context, and expands. Terms the context does not define are listed, never dropped."
            issues={output.wellFormedness}
          />
          <LayerSection
            title="Layer 2 — Structural (canonical JSON Schema)"
            note={structuralNote}
            issues={structural ? structuralIssues(structural) : []}
          />
          <LayerSection
            title="Layer 3 — Semantic sanity"
            note="Identity IRIs, quantities carrying a value and a unit, and references shaped like our identifiers."
            issues={output.semantic}
          />
        </div>
      ) : null}
    </div>
  );
}

function ViewBody({
  view,
  form,
  output,
  summary,
}: {
  view: ViewKind;
  form: "canonical" | "raw";
  output: WorkbenchOutput;
  summary: ReturnType<typeof extractSummary> | null;
}) {
  if (view === "summary") {
    return summary ? <SummaryView model={summary} /> : <NoCanonical />;
  }
  if (view === "table") {
    return summary ? <TableView model={summary} /> : <NoCanonical />;
  }
  if (view === "tree") {
    if (form === "canonical") {
      if (!output.framed) return <NoCanonical />;
      return (
        <JsonLdTree
          data={stripContext(output.framed)}
          context={(output.framed["@context"] as Record<string, unknown>) ?? {}}
        />
      );
    }
    return output.parsed ? (
      <JsonLdTree data={output.parsed} context={effectiveContext(output.parsed)} />
    ) : (
      <NoCanonical />
    );
  }
  const data = form === "canonical" ? output.framed : output.parsed;
  return data ? <JsonView data={data} /> : <NoCanonical />;
}

function NoCanonical() {
  return (
    <div className="flex min-h-[12rem] items-center justify-center rounded-xl border border-dashed border-border bg-surface p-6 text-center text-sm text-ink-faint">
      No canonical view — the document did not expand. See the well-formedness issues below.
    </div>
  );
}

function ExamplePicker({ onPick }: { onPick: (doc: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="text-brand-600 hover:text-brand-700">
        Load an example…
      </button>
      {open ? (
        <div className="absolute right-0 z-10 mt-1 w-72 rounded-lg border border-border bg-white p-1 shadow-lg">
          {jsonldGallery.map((entry) => (
            <button
              key={entry.slug}
              onClick={() => {
                onPick(JSON.stringify(entry.jsonld, null, 2));
                setOpen(false);
              }}
              className="block w-full rounded-md px-3 py-2 text-left text-xs text-ink hover:bg-tint"
            >
              {entry.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

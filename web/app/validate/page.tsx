"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { validateRecord, type Issue, type ValidationResult } from "@/lib/validate";
import { cellSpecCanonical } from "@/lib/examples";
import { site } from "@/lib/site";

// The JSON-LD workbench pulls in the jsonld library; load it (and the library)
// only when the visitor opens that tab, so the record validator and every other
// page stay light.
const JsonLdWorkbench = dynamic(() => import("@/components/jsonld-workbench"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[28rem] items-center justify-center rounded-xl border border-dashed border-border bg-surface text-sm text-ink-faint">
      Loading the JSON-LD workbench…
    </div>
  ),
});

const SAMPLE = JSON.stringify(cellSpecCanonical, null, 2);

// A deliberately broken variant of the sample: a typo'd field, a bare-number
// quantity, and a non-IRI id, the three classic newcomer mistakes. Lets a
// visitor see the validator TEACH before pasting their own record.
const BROKEN_SAMPLE = JSON.stringify(
  (() => {
    const doc = JSON.parse(JSON.stringify(cellSpecCanonical)) as {
      cell_spec: Record<string, unknown>;
      properties?: Record<string, unknown>;
    };
    doc.cell_spec.manufacture = "A123"; // typo: should be manufacturer
    doc.cell_spec.id = "my-cell-1"; // not a canonical IRI
    doc.properties = { ...doc.properties, nominal_capacity: 2.5 }; // bare number
    return doc;
  })(),
  null,
  2,
);

function IssueRow({ issue }: { issue: Issue }) {
  const isError = issue.severity === "error";
  return (
    <li className="flex items-start gap-3 rounded-lg border border-border bg-surface p-3">
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

function RecordValidator() {
  const [input, setInput] = useState(SAMPLE);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function run(next?: string) {
    const text = next ?? input;
    if (next !== undefined) setInput(next);
    setResult(validateRecord(text));
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    run(await file.text());
  }

  const errors = result?.issues.filter((i) => i.severity === "error") ?? [];
  const warnings = result?.issues.filter((i) => i.severity === "warning") ?? [];
  // The record validator recognizes JSON-LD and points at the other tab.
  const looksJsonLd = result?.issues.some((i) => /JSON-LD document/.test(i.message)) ?? false;

  return (
    <>
      <p className="mb-6 max-w-prose text-sm text-ink-muted">
        Paste the <em>canonical record JSON</em>, the object your authoring code produces. It is checked against the{" "}
        same JSON Schemas the Python library and the registry&rsquo;s publish gate enforce, so the browser and{" "}
        <code className="text-sm">battinfo validate</code> give the same structural verdict.
      </p>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Record JSON</h2>
            <div className="flex gap-3 text-xs font-medium">
              <button onClick={() => run(SAMPLE)} className="text-brandtext hover:text-brandtext">
                Load a valid record
              </button>
              <button onClick={() => run(BROKEN_SAMPLE)} className="text-brandtext hover:text-brandtext">
                See it catch mistakes
              </button>
              <button onClick={() => fileInput.current?.click()} className="text-brandtext hover:text-brandtext">
                Open a file…
              </button>
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
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
            className="h-[28rem] w-full resize-none rounded-xl border border-border bg-code-bg p-4 font-mono text-sm text-code-fg focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          <button
            onClick={() => run()}
            className="mt-4 w-full rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-fg transition hover:opacity-90"
          >
            Validate
          </button>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Result</h2>
          {!result ? (
            <div className="flex h-[28rem] items-center justify-center rounded-xl border border-dashed border-border bg-surface text-sm text-ink-faint">
              Run validation to see results.
            </div>
          ) : (
            <div className="space-y-4">
              <div
                className={`rounded-xl border p-4 ${
                  result.ok ? "border-volt-200 bg-volt-50" : "border-error/30 bg-error-tint"
                }`}
              >
                <p className={`text-sm font-semibold ${result.ok ? "text-volt-700" : "text-error"}`}>
                  {result.ok ? "Valid against the canonical schema" : "Validation failed"}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  {result.recordType ? (
                    <>
                      detected type <span className="font-mono">{result.recordType}</span> ·{" "}
                    </>
                  ) : null}
                  {errors.length} error{errors.length === 1 ? "" : "s"} · {warnings.length} warning
                  {warnings.length === 1 ? "" : "s"}
                </p>
              </div>

              {errors.length > 0 && (
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-error">Errors</h3>
                  <ul className="space-y-2">
                    {errors.map((issue, i) => (
                      <IssueRow key={i} issue={issue} />
                    ))}
                  </ul>
                </div>
              )}
              {warnings.length > 0 && (
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-warning">Warnings</h3>
                  <ul className="space-y-2">
                    {warnings.map((issue, i) => (
                      <IssueRow key={i} issue={issue} />
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Reproduce canonically */}
      <section className="mt-12 rounded-2xl border border-border bg-surface p-6">
        <h2 className="text-lg font-semibold text-ink">The full verdict, locally</h2>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          For the authoritative check, schema, references, semantics, and publication policies, run the same record
          through the CLI:
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-code-bg p-4 text-sm">
          <code className="font-mono text-code-fg">{`battinfo validate my-record.json --policy strict --format json`}</code>
        </pre>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link href="/publish" className="font-semibold text-brandtext hover:text-brandtext">
            Ready? Publish your data →
          </Link>
          <a
            href={`${site.github}/blob/main/docs/validation-contract.md`}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-brandtext hover:text-brandtext"
          >
            Read the validation contract →
          </a>
        </div>
      </section>
    </>
  );
}

type Mode = "record" | "jsonld";

export default function ValidatePage() {
  const [mode, setMode] = useState<Mode>("record");

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Validate and explore</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Check a <strong>canonical record</strong> against the schemas the library enforces, or view and check a{" "}
          <strong>published JSON-LD document</strong> as linked data, both in the browser, with nothing leaving the
          page.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-brand-200 bg-tint px-2.5 py-1 font-medium text-brandtext">
            canonical JSON Schemas · drift-checked in CI
          </span>
          <span className="text-ink-faint">
            domain-battery {site.versions.domainBattery} · {site.versions.schema}
          </span>
        </div>
        <p className="mt-4 text-sm text-ink-muted">
          Building a new record from scratch? Start in the{" "}
          <Link href="/create" className="font-semibold text-brandtext hover:text-brandtext">
            Playground
          </Link>
          , which gives you a working template and checks it as you type.
        </p>
      </header>

      <div className="mt-8 inline-flex rounded-lg border border-border p-1">
        {(
          [
            ["record", "Canonical record"],
            ["jsonld", "JSON-LD document"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={`rounded-md px-4 py-2 text-sm font-medium transition ${
              mode === value ? "bg-tint text-brandtext" : "text-ink-muted hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-8">
        {mode === "record" ? (
          <RecordValidator />
        ) : (
          <>
            <p className="mb-6 max-w-prose text-sm text-ink-muted">
              Paste or drop the <em>published JSON-LD</em>, the linked-data form generated from a record. It is
              expanded and re-nested to our canonical shape in the browser, then checked in three independent layers.
              Nothing is sent anywhere.
            </p>
            <JsonLdWorkbench />
          </>
        )}
      </div>
    </div>
  );
}

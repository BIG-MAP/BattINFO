"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { validateRecord, type Issue, type ValidationResult } from "@/lib/validate";
import { cellSpecCanonical } from "@/lib/examples";
import { site } from "@/lib/site";

const SAMPLE = JSON.stringify(cellSpecCanonical, null, 2);

// A deliberately broken variant of the sample: a typo'd field, a bare-number
// quantity, and a non-IRI id — the three classic newcomer mistakes. Lets a
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
    <li className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3">
      <span
        className={`mt-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
          isError ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
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

export default function ValidatePage() {
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

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Validate a record</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Paste or drop any BattINFO record. It is checked against the{" "}
          <em>same canonical JSON Schemas</em> the Python library and the
          registry&rsquo;s publish gate enforce — the browser and{" "}
          <code className="text-sm">battinfo validate</code> give the same
          structural verdict.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-brand-200 bg-brand-50 px-2.5 py-1 font-medium text-brand-700">
            canonical JSON Schemas · drift-checked in CI
          </span>
          <span className="text-ink-faint">
            domain-battery {site.versions.domainBattery} · {site.versions.schema}
          </span>
        </div>
        <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-ink-muted">
          This is the structural layer. The Python package additionally runs
          semantic rules, SHACL shapes, and referential-integrity checks that
          need your full record set — run those locally before publishing.
        </p>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Record JSON</h2>
            <div className="flex gap-3 text-xs font-medium">
              <button
                onClick={() => run(SAMPLE)}
                className="text-brand-600 hover:text-brand-700"
              >
                Load a valid record
              </button>
              <button
                onClick={() => run(BROKEN_SAMPLE)}
                className="text-brand-600 hover:text-brand-700"
              >
                See it catch mistakes
              </button>
              <button
                onClick={() => fileInput.current?.click()}
                className="text-brand-600 hover:text-brand-700"
              >
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
            className="h-[28rem] w-full resize-none rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-slate-100 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          <button
            onClick={() => run()}
            className="mt-4 w-full rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-700"
          >
            Validate
          </button>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Result</h2>
          {!result ? (
            <div className="flex h-[28rem] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-ink-faint">
              Run validation to see results.
            </div>
          ) : (
            <div className="space-y-4">
              <div
                className={`rounded-xl border p-4 ${
                  result.ok ? "border-volt-200 bg-volt-50" : "border-red-200 bg-red-50"
                }`}
              >
                <p className={`text-sm font-semibold ${result.ok ? "text-volt-700" : "text-red-700"}`}>
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
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-red-600">
                    Errors
                  </h3>
                  <ul className="space-y-2">
                    {errors.map((issue, i) => (
                      <IssueRow key={i} issue={issue} />
                    ))}
                  </ul>
                </div>
              )}
              {warnings.length > 0 && (
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-amber-600">
                    Warnings
                  </h3>
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
      <section className="mt-12 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-ink">The full verdict, locally</h2>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          For the authoritative check — schema, references, semantics, and
          publication policies — run the same record through the CLI:
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-950 p-4 text-sm">
          <code className="font-mono text-slate-100">{`battinfo validate my-record.json --policy strict --format json`}</code>
        </pre>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link href="/publish" className="font-semibold text-brand-600 hover:text-brand-700">
            Ready? Publish your data →
          </Link>
          <a
            href={`${site.github}/blob/main/docs/validation-contract.md`}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-brand-600 hover:text-brand-700"
          >
            Read the validation contract →
          </a>
        </div>
      </section>
    </div>
  );
}

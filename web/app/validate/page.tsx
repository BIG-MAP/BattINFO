"use client";

import { useState } from "react";
import Link from "next/link";
import { validateCellType, type Issue } from "@/lib/validate";
import { cellTypeInput } from "@/lib/examples";
import { site } from "@/lib/site";

const SAMPLE = JSON.stringify(cellTypeInput, null, 2);

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
  const [result, setResult] = useState<ReturnType<typeof validateCellType> | null>(null);

  function run() {
    setResult(validateCellType(input));
  }

  const errors = result?.issues.filter((i) => i.severity === "error") ?? [];
  const warnings = result?.issues.filter((i) => i.severity === "warning") ?? [];

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Validate a record</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Paste a cell-type record to check it against BattINFO&rsquo;s core
          structural invariants — in your browser, instantly.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-medium text-amber-800">
            structural pre-check
          </span>
          <span className="text-ink-faint">
            Canonical engine: battinfo · domain-battery {site.versions.domainBattery} · {site.versions.schema}
          </span>
        </div>
        <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-ink-muted">
          This is a lightweight structural pre-check. The authoritative,
          multi-layer validation — JSON Schema, Pydantic, JSON-LD URDNA2015,
          semantic rules, and referential integrity, with stable issue codes and
          policies (<span className="font-mono text-xs">default / strict / publisher / ingest</span>) —
          runs in the Python package and registry.
        </p>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Record JSON</h2>
            <button
              onClick={() => {
                setInput(SAMPLE);
                setResult(null);
              }}
              className="text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              Reset to sample
            </button>
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            spellCheck={false}
            className="h-[28rem] w-full resize-none rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-slate-100 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          <button
            onClick={run}
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
                  {result.ok ? "Structurally valid" : "Validation failed"}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
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
        <h2 className="text-lg font-semibold text-ink">Validate canonically</h2>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          For the authoritative verdict — schema, references, semantics, and
          publication checks under a named policy — run the same record through the
          package or CLI:
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-950 p-4 text-sm">
          <code className="font-mono text-slate-100">{`battinfo validate cell-type.json --policy strict --format json`}</code>
        </pre>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link href="/convert" className="font-semibold text-brand-600 hover:text-brand-700">
            Convert this record to JSON-LD →
          </Link>
          <a
            href={`${site.github}/blob/master/docs/validation-contract.md`}
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

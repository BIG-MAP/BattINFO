"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { convertCellType } from "@/lib/convert";
import { cellTypeInput } from "@/lib/examples";
import { site } from "@/lib/site";

const SAMPLE = JSON.stringify(cellTypeInput, null, 2);

type Tab = "domain-battery" | "converter-compatible" | "authored";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "domain-battery", label: "domain-battery", hint: "Canonical EMMO JSON-LD" },
  { id: "converter-compatible", label: "converter-compatible", hint: "Legacy migration shape" },
  { id: "authored", label: "authored", hint: "Your input, untouched" },
];

export default function ConvertPage() {
  const [input, setInput] = useState(SAMPLE);
  const [tab, setTab] = useState<Tab>("domain-battery");

  // Recompute on every keystroke — the live-playground feel.
  const result = useMemo(() => convertCellType(input), [input]);

  const output = useMemo(() => {
    if (result.error) return result.error;
    if (tab === "authored") return input;
    const value = tab === "domain-battery" ? result.domainBattery : result.converterCompatible;
    return JSON.stringify(value, null, 2);
  }, [result, tab, input]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Convert to Linked Data</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Author plain JSON on the left; watch it become ontology-aligned JSON-LD
          on the right, live. This is the transform that makes a battery record
          machine-readable — and resolvable.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-medium text-amber-800">
            structural pre-check · illustrative
          </span>
          <span className="text-ink-faint">
            Canonical engine: battinfo · domain-battery {site.versions.domainBattery}
          </span>
        </div>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-2">
        {/* Input */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">
              Authored JSON
            </h2>
            <button
              onClick={() => setInput(SAMPLE)}
              className="text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              Reset to sample
            </button>
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            spellCheck={false}
            className="h-[30rem] w-full resize-none rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-slate-100 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
        </div>

        {/* Output */}
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                title={t.hint}
                className={`rounded-md px-2.5 py-1.5 font-mono text-xs transition ${
                  tab === t.id
                    ? "bg-brand-600 text-white"
                    : "text-ink-muted hover:bg-slate-100 hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
            <pre className="h-[30rem] overflow-auto p-4 text-sm leading-relaxed">
              <code
                className={`font-mono ${result.error ? "text-red-300" : "text-slate-100"}`}
              >
                {output}
              </code>
            </pre>
          </div>
        </div>
      </div>

      {/* Transform notes — lossy areas are surfaced, never hidden */}
      {!result.error && result.notes.length > 0 && (
        <section className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">
            Transform notes
          </h3>
          <ul className="mt-3 space-y-1.5 text-sm text-ink-muted">
            {result.notes.map((n, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-2 h-1 w-1 flex-none rounded-full bg-ink-faint" />
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* What changed — the teaching panel */}
      <section className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="prose-card">
          <h3 className="text-base font-semibold text-ink">@type stacking</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            One cell is simultaneously a <span className="font-mono text-xs">BatteryCell</span>, a
            geometry type, a chemistry type, and a cathode-material type — EMMO multiple
            inheritance, not a single flat label.
          </p>
        </div>
        <div className="prose-card">
          <h3 className="text-base font-semibold text-ink">Quantity pattern</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            Each value becomes{" "}
            <span className="font-mono text-xs">hasProperty → hasNumericalPart → hasNumericalValue</span>,
            with the unit as a full EMMO/QUDT IRI. Units are never implicit strings.
          </p>
        </div>
        <div className="prose-card">
          <h3 className="text-base font-semibold text-ink">Two views, one model</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            The same record exports as canonical{" "}
            <span className="font-mono text-xs">domain-battery</span> JSON-LD or as the{" "}
            <span className="font-mono text-xs">converter-compatible</span> shape for migrating
            legacy BattINFO-Converter tooling.
          </p>
        </div>
      </section>

      {/* Reproduce in code */}
      <section className="mt-10 rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-lg font-semibold text-ink">Reproduce this canonically</h3>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          The browser preview is illustrative. The deterministic, mapping-driven
          transform runs in the Python package and yields valid RDF:
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-950 p-4 text-sm">
          <code className="font-mono text-slate-100">{`from battinfo.transform import to_jsonld

jsonld = to_jsonld(record, target="domain-battery")`}</code>
        </pre>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link href="/validate" className="font-semibold text-brand-600 hover:text-brand-700">
            Validate this record →
          </Link>
          <Link href="/docs#schemas" className="font-semibold text-brand-600 hover:text-brand-700">
            Read the schemas →
          </Link>
        </div>
      </section>
    </div>
  );
}

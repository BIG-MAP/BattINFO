import type { Metadata } from "next";
import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { cellSpecInput, cellSpecJsonLd } from "@/lib/examples";

export const metadata: Metadata = {
  title: "Examples",
  description: "See how a plain-JSON battery cell record becomes EMMO-aligned JSON-LD with BattINFO.",
};

export default function ExamplesPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Examples</h1>
        <p className="mt-4 text-lg text-ink-muted">
          The same cell, two representations. You author the readable JSON on the
          left; BattINFO emits the ontology-aligned JSON-LD on the right.
        </p>
      </header>

      <section className="mt-12">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">
            Cell spec · A123 ANR26650M1-B
          </h2>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 font-mono text-xs text-ink-muted">
            cylindrical · LFP · Li-ion
          </span>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Input — authored JSON</h3>
            <CodeBlock label="cell-spec.json" code={JSON.stringify(cellSpecInput, null, 2)} />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-brand-600">Output — EMMO JSON-LD</h3>
            <CodeBlock label="cell-spec.jsonld" code={JSON.stringify(cellSpecJsonLd, null, 2)} />
          </div>
        </div>
      </section>

      <section className="mt-12 rounded-2xl border border-slate-200 bg-slate-50 p-6">
        <h3 className="text-lg font-semibold text-ink">What changed in the transform</h3>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed text-ink-muted">
          <li>
            <span className="font-medium text-ink">@type stacking</span> — a cylindrical LFP cell is simultaneously{" "}
            <span className="font-mono text-xs">BatteryCell</span>,{" "}
            <span className="font-mono text-xs">CylindricalBattery</span>,{" "}
            <span className="font-mono text-xs">LithiumIonBattery</span>, and{" "}
            <span className="font-mono text-xs">LithiumIronPhosphateBattery</span>.
          </li>
          <li>
            <span className="font-medium text-ink">Quantity pattern</span> — each value becomes{" "}
            <span className="font-mono text-xs">hasProperty → hasNumericalPart → hasNumericalValue</span>, with the unit
            as a full EMMO/QUDT IRI rather than a bare string.
          </li>
          <li>
            <span className="font-medium text-ink">Persistent IRI</span> — the record is addressed by a stable{" "}
            <span className="font-mono text-xs">w3id.org/battinfo/spec/…</span> identifier.
          </li>
        </ul>
        <p className="mt-4 text-xs text-ink-faint">
          Illustrative and abbreviated. The canonical, deterministic transform lives in the Python package; more
          worked records are in the repo under <span className="font-mono">examples/</span>.
        </p>
      </section>

      <div className="mt-10">
        <Link href="/validate" className="text-sm font-semibold text-brand-600 hover:text-brand-700">
          Validate your own record →
        </Link>
      </div>
    </div>
  );
}

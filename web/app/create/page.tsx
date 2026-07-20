"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { CodeTabs } from "@/components/code-tabs";
import {
  type CellDraft,
  type DraftProperty,
  FORMATS,
  CHEMISTRIES,
  PROPERTY_CATALOG,
  toRecord,
  toPython,
  toJsonLd,
} from "@/lib/create-model";

const DEFAULT: CellDraft = {
  name: "",
  manufacturer: "A123",
  model: "ANR26650M1-B",
  format: "cylindrical",
  chemistry: "Li-ion",
  positiveBasis: "LFP",
  negativeBasis: "",
  properties: [
    { key: "nominal_capacity", value: "2.5", unit: "Ah" },
    { key: "nominal_voltage", value: "3.3", unit: "V" },
  ],
};

const inputClass =
  "w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</span>
      {children}
    </label>
  );
}

export default function CreatePage() {
  const [draft, setDraft] = useState<CellDraft>(DEFAULT);

  function set(patch: Partial<CellDraft>) {
    setDraft((d) => ({ ...d, ...patch }));
  }

  function updateProperty(index: number, patch: Partial<DraftProperty>) {
    setDraft((d) => ({
      ...d,
      properties: d.properties.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    }));
  }

  function addProperty() {
    const used = new Set(draft.properties.map((p) => p.key));
    const next = PROPERTY_CATALOG.find((c) => !used.has(c.key)) ?? PROPERTY_CATALOG[0];
    setDraft((d) => ({
      ...d,
      properties: [...d.properties, { key: next.key, value: "", unit: next.units[0] }],
    }));
  }

  function removeProperty(index: number) {
    setDraft((d) => ({ ...d, properties: d.properties.filter((_, i) => i !== index) }));
  }

  const tabs = useMemo(
    () => [
      { label: "Python", blockLabel: "authoring code", code: toPython(draft) },
      { label: "JSON", blockLabel: "canonical record", code: JSON.stringify(toRecord(draft), null, 2) },
      { label: "JSON-LD", blockLabel: "published (compact)", code: JSON.stringify(toJsonLd(draft), null, 2) },
    ],
    [draft],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Create a record</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Build a simple cell spec on the left and watch it become the three forms you work with: the{" "}
          <strong>Python</strong> that authors it, the <strong>canonical record</strong>, and the published{" "}
          <strong>JSON-LD</strong>. Everything updates as you type — nothing leaves the page.
        </p>
        <p className="mt-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm text-ink-muted">
          A quick sketch, not the full model. The identifier is minted when you save;{" "}
          <Link href="/validate" className="font-semibold text-brand-600 hover:text-brand-700">
            check any record
          </Link>{" "}
          against the canonical schemas, or read the{" "}
          <Link href="/docs" className="font-semibold text-brand-600 hover:text-brand-700">
            authoring guide
          </Link>{" "}
          for the complete surface.
        </p>
      </header>

      <div className="mt-10 grid gap-8 lg:grid-cols-2">
        {/* Builder */}
        <div className="space-y-6">
          <div className="rounded-2xl border border-border bg-white p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-ink-faint">Identity</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Manufacturer">
                <input className={inputClass} value={draft.manufacturer} onChange={(e) => set({ manufacturer: e.target.value })} />
              </Field>
              <Field label="Model">
                <input className={inputClass} value={draft.model} onChange={(e) => set({ model: e.target.value })} />
              </Field>
              <Field label="Format">
                <select className={inputClass} value={draft.format} onChange={(e) => set({ format: e.target.value })}>
                  {FORMATS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Chemistry">
                <select className={inputClass} value={draft.chemistry} onChange={(e) => set({ chemistry: e.target.value })}>
                  {CHEMISTRIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Positive electrode">
                <input className={inputClass} value={draft.positiveBasis} onChange={(e) => set({ positiveBasis: e.target.value })} placeholder="e.g. LFP" />
              </Field>
              <Field label="Negative electrode">
                <input className={inputClass} value={draft.negativeBasis} onChange={(e) => set({ negativeBasis: e.target.value })} placeholder="e.g. graphite" />
              </Field>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-white p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Properties</h2>
              <button onClick={addProperty} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                + Add property
              </button>
            </div>
            <div className="space-y-3">
              {draft.properties.length === 0 ? (
                <p className="text-sm text-ink-faint">No properties yet — add one to see it appear as a quantity.</p>
              ) : null}
              {draft.properties.map((prop, i) => {
                const catalog = PROPERTY_CATALOG.find((c) => c.key === prop.key) ?? PROPERTY_CATALOG[0];
                return (
                  <div key={i} className="flex items-end gap-2">
                    <div className="flex-1">
                      <select
                        className={inputClass}
                        value={prop.key}
                        onChange={(e) => {
                          const cat = PROPERTY_CATALOG.find((c) => c.key === e.target.value)!;
                          updateProperty(i, { key: cat.key, unit: cat.units.includes(prop.unit) ? prop.unit : cat.units[0] });
                        }}
                      >
                        {PROPERTY_CATALOG.map((c) => (
                          <option key={c.key} value={c.key}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="w-24">
                      <input
                        type="number"
                        className={inputClass}
                        value={prop.value}
                        onChange={(e) => updateProperty(i, { value: e.target.value })}
                        placeholder="value"
                      />
                    </div>
                    <div className="w-24">
                      <select className={inputClass} value={prop.unit} onChange={(e) => updateProperty(i, { unit: e.target.value })}>
                        {catalog.units.map((u) => (
                          <option key={u} value={u}>
                            {u}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button
                      onClick={() => removeProperty(i)}
                      aria-label="Remove property"
                      className="mb-1 rounded-md px-2 py-1 text-sm text-ink-faint hover:bg-error-tint hover:text-error"
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Live serializations */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Serializations</h2>
          <CodeTabs tabs={tabs} />
          <p className="mt-3 text-xs text-ink-faint">
            The JSON-LD is the compact form; it references our hosted <code className="text-xs">@context</code>. Open it
            in{" "}
            <Link href="/validate" className="font-semibold text-brand-600 hover:text-brand-700">
              the JSON-LD workbench
            </Link>{" "}
            to expand and check it.
          </p>
        </div>
      </div>
    </div>
  );
}

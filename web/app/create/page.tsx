"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { CodeTabs } from "@/components/code-tabs";
import {
  type ObjectDef,
  type DraftProperty,
  type Values,
  OBJECT_TYPES,
  draftStatus,
} from "@/lib/create-model";

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</span>
      {children}
    </label>
  );
}

const STATUS = {
  green: { text: "Looks valid against the schemas", cls: "border-volt-200 bg-volt-50 text-volt-700" },
  yellow: { text: "Some warnings", cls: "border-warning/30 bg-warning-tint text-warning" },
  red: { text: "Some fields need fixing", cls: "border-error/30 bg-error-tint text-error" },
} as const;

export default function PlaygroundPage() {
  const [typeKey, setTypeKey] = useState(OBJECT_TYPES[0].key);
  const type = OBJECT_TYPES.find((t) => t.key === typeKey) as ObjectDef;
  const [values, setValues] = useState<Values>(OBJECT_TYPES[0].defaults);
  const [properties, setProperties] = useState<DraftProperty[]>(OBJECT_TYPES[0].defaultProperties ?? []);

  function selectType(key: string) {
    const next = OBJECT_TYPES.find((t) => t.key === key) as ObjectDef;
    setTypeKey(key);
    setValues(next.defaults);
    setProperties(next.defaultProperties ?? []);
  }

  function setField(key: string, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  function updateProperty(index: number, patch: Partial<DraftProperty>) {
    setProperties((ps) => ps.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function addProperty() {
    if (!type.properties) return;
    const used = new Set(properties.map((p) => p.key));
    const next = type.properties.find((c) => !used.has(c.key)) ?? type.properties[0];
    setProperties((ps) => [...ps, { key: next.key, value: "", unit: next.units[0] }]);
  }

  const record = useMemo(() => type.toRecord(values, properties), [type, values, properties]);
  const status = useMemo(() => draftStatus(record), [record]);
  const tabs = useMemo(
    () => [
      { label: "Python", blockLabel: "authoring code", code: type.toPython(values, properties) },
      { label: "JSON", blockLabel: "canonical record", code: JSON.stringify(record, null, 2) },
      { label: "JSON-LD", blockLabel: "published (compact)", code: JSON.stringify(type.toJsonLd(values, properties), null, 2) },
    ],
    [type, values, properties, record],
  );

  function renderField(f: (typeof type.fields)[number]) {
    if (f.kind === "select") {
      return (
        <select className={inputClass} value={values[f.key] ?? ""} onChange={(e) => setField(f.key, e.target.value)}>
          {(f.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        type={f.kind === "date" ? "date" : "text"}
        className={inputClass}
        value={values[f.key] ?? ""}
        placeholder={f.placeholder}
        onChange={(e) => setField(f.key, e.target.value)}
      />
    );
  }

  const groups = type.sections ?? [{ key: "", title: type.label, blurb: type.blurb }];

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">battinfo playground</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Build one of the core objects on the left. Watch it turn into the three forms you work with: the Python that
          authors it, the canonical record, and the published JSON-LD. It updates as you type, and nothing leaves the
          page.
        </p>
        <p className="mt-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm text-ink-muted">
          This is a quick sketch, not the full model. Identifiers are added when you save. To check a finished record,
          use{" "}
          <Link href="/validate" className="font-semibold text-brand-600 hover:text-brand-700">
            Validate
          </Link>
          , or read the{" "}
          <Link href="/docs" className="font-semibold text-brand-600 hover:text-brand-700">
            authoring guide
          </Link>
          .
        </p>
      </header>

      <div className="mt-8 flex flex-wrap gap-2">
        {OBJECT_TYPES.map((t) => (
          <button
            key={t.key}
            onClick={() => selectType(t.key)}
            className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${
              t.key === typeKey
                ? "border-brand-300 bg-brand-50 text-brand-700"
                : "border-border bg-surface text-ink-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-2">
        {/* Builder */}
        <div className="space-y-6">
          {groups.map((section) => {
            const fields = type.fields.filter((f) => (f.section ?? "") === section.key);
            if (fields.length === 0) return null;
            return (
              <div key={section.key || type.key} className="rounded-2xl border border-border bg-surface p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">{section.title}</h2>
                <p className="mb-4 mt-1 text-xs text-ink-faint">{section.blurb}</p>
                <div className="grid gap-4 sm:grid-cols-2">
                  {fields.map((f) => (
                    <Field key={f.key} label={f.label}>
                      {renderField(f)}
                    </Field>
                  ))}
                </div>
              </div>
            );
          })}

          {type.properties ? (
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Properties</h2>
                <button onClick={addProperty} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                  + Add property
                </button>
              </div>
              <div className="space-y-3">
                {properties.length === 0 ? (
                  <p className="text-sm text-ink-faint">No properties yet. Add one to see it appear as a quantity.</p>
                ) : null}
                {properties.map((prop, i) => {
                  const catalog = type.properties!.find((c) => c.key === prop.key) ?? type.properties![0];
                  return (
                    <div key={i} className="flex items-end gap-2">
                      <div className="flex-1">
                        <select
                          className={inputClass}
                          value={prop.key}
                          onChange={(e) => {
                            const cat = type.properties!.find((c) => c.key === e.target.value)!;
                            updateProperty(i, { key: cat.key, unit: cat.units.includes(prop.unit) ? prop.unit : cat.units[0] });
                          }}
                        >
                          {type.properties!.map((c) => (
                            <option key={c.key} value={c.key}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="w-24">
                        <input type="number" className={inputClass} value={prop.value} onChange={(e) => updateProperty(i, { value: e.target.value })} placeholder="value" />
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
                        onClick={() => setProperties((ps) => ps.filter((_, j) => j !== i))}
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
          ) : null}
        </div>

        {/* Live output */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">Serializations</h2>
            <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS[status.level].cls}`}>
              {status.level === "green" ? "✓ " : ""}
              {STATUS[status.level].text}
            </span>
          </div>
          <CodeTabs tabs={tabs} />
          {status.issues.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {status.issues.slice(0, 6).map((issue, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span
                    className={`mt-px rounded px-1 py-0.5 font-mono text-[10px] font-bold uppercase ${
                      issue.severity === "error" ? "bg-error-tint text-error" : "bg-warning-tint text-warning"
                    }`}
                  >
                    {issue.severity}
                  </span>
                  <span className="text-ink-muted">
                    <span className="font-mono text-ink-faint">{issue.path}</span> {issue.message}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-ink-faint">
              Checked in the browser against the canonical schemas. The CLI runs the full check on save.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

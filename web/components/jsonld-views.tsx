"use client";

// Reader-friendly views of a framed JSON-LD document, aimed at lab engineers
// rather than linked-data specialists: a datasheet-style Summary, a plain
// Table, and formatted JSON. The interactive Tree lives in jsonld-tree.tsx.

import type { SummaryModel } from "@/lib/jsonld-workbench";

// Common EMMO unit names rendered as the symbol an engineer expects.
const UNIT_SYMBOL: Record<string, string> = {
  AmpereHour: "Ah",
  MilliAmpereHour: "mAh",
  Volt: "V",
  MilliVolt: "mV",
  KiloVolt: "kV",
  Ampere: "A",
  MilliAmpere: "mA",
  Watt: "W",
  KiloWatt: "kW",
  WattHour: "Wh",
  KiloWattHour: "kWh",
  MegaWattHour: "MWh",
  Ohm: "Ω",
  MilliOhm: "mΩ",
  Gram: "g",
  Kilogram: "kg",
  MilliGram: "mg",
  MilliMetre: "mm",
  CentiMetre: "cm",
  Metre: "m",
  MicroMetre: "µm",
  Litre: "L",
  MilliLitre: "mL",
  Percent: "%",
  DegreeCelsius: "°C",
  Kelvin: "K",
  Hour: "h",
  Minute: "min",
  Second: "s",
  WattHourPerKilogram: "Wh/kg",
  WattHourPerLitre: "Wh/L",
  WattPerKilogram: "W/kg",
  UnitOne: "",
};

function unit(u: string | null): string {
  if (!u) return "";
  return UNIT_SYMBOL[u] ?? u;
}

function shortId(id: string | null): string {
  if (!id) return "";
  const cut = Math.max(id.lastIndexOf("/"), id.lastIndexOf(":"));
  return cut >= 0 ? id.slice(cut + 1) : id;
}

function EmptyView({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[12rem] items-center justify-center rounded-xl border border-dashed border-border bg-surface p-6 text-center text-sm text-ink-faint">
      {children}
    </div>
  );
}

export function SummaryView({ model }: { model: SummaryModel }) {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border bg-surface p-6">
        <h3 className="text-2xl font-bold tracking-tight text-ink">{model.title ?? "Untitled record"}</h3>
        <p className="mt-1 text-sm text-ink-muted">
          {[model.model, model.manufacturer].filter(Boolean).join(" · ") || "no model or manufacturer stated"}
        </p>
        {model.id ? (
          <p className="mt-1 font-mono text-xs text-ink-faint" title={model.id}>
            {shortId(model.id)}
          </p>
        ) : null}
        {model.types.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {model.types.map((t) => (
              <span
                key={t}
                className="rounded-full border border-brand-200 bg-tint px-2.5 py-1 text-xs font-medium text-brandtext"
              >
                {t}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {model.properties.length > 0 ? (
        <div>
          <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Properties</h4>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {model.properties.map((p, i) => (
              <div key={`${p.label}-${i}`} className="rounded-xl border border-border bg-surface p-3">
                <p className="text-xs text-ink-muted">{p.label}</p>
                <p className="mt-1 font-mono text-lg text-ink">
                  {p.value}
                  {p.unit ? <span className="ml-1 text-sm text-ink-muted">{unit(p.unit)}</span> : null}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {model.components.length > 0 ? (
        <div>
          <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-ink-faint">Components</h4>
          <div className="space-y-2">
            {model.components.map((c, i) => (
              <div
                key={`${c.relation}-${i}`}
                className="flex flex-wrap items-baseline gap-2 rounded-lg border border-border bg-surface px-3 py-2"
              >
                <span className="text-xs text-ink-faint">{c.relation}</span>
                <span className="text-sm text-ink">{c.label}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {model.properties.length === 0 && model.components.length === 0 ? (
        <EmptyView>No properties or components found in this document.</EmptyView>
      ) : null}
    </div>
  );
}

export function TableView({ model }: { model: SummaryModel }) {
  const identity: [string, string | null][] = [
    ["Name", model.title],
    ["Model", model.model],
    ["Manufacturer", model.manufacturer],
    ["Identifier", model.id],
    ["Types", model.types.join(", ") || null],
  ];
  return (
    <div className="space-y-6">
      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <tbody>
            {identity.map(([field, value]) => (
              <tr key={field} className="border-b border-border last:border-0">
                <th className="w-40 bg-surface px-4 py-2 text-left font-medium text-ink-muted">{field}</th>
                <td className="px-4 py-2 font-mono text-xs text-ink">{value ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {model.properties.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface text-left text-xs uppercase tracking-wider text-ink-faint">
                <th className="px-4 py-2 font-semibold">Property</th>
                <th className="px-4 py-2 font-semibold">Value</th>
                <th className="px-4 py-2 font-semibold">Unit</th>
              </tr>
            </thead>
            <tbody>
              {model.properties.map((p, i) => (
                <tr key={`${p.label}-${i}`} className="border-b border-border last:border-0">
                  <td className="px-4 py-2 text-ink">{p.label}</td>
                  <td className="px-4 py-2 font-mono text-ink">{p.value}</td>
                  <td className="px-4 py-2 text-ink-muted">{unit(p.unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyView>This document has no quantitative properties to tabulate.</EmptyView>
      )}
    </div>
  );
}


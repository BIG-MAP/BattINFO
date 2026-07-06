"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { curatedProperties, curatedUnits } from "@/lib/properties.generated";
import { site } from "@/lib/site";

/**
 * The property explorer: `battinfo properties show` for people who have not
 * installed anything. Every row is a curated mapping from an authoring key
 * (what you type) to an EMMO class (what the world understands) — the single
 * strongest "real semantics, no install" proof on the site. Data is generated
 * from the canonical mapping tables and drift-checked in CI.
 */
export default function PropertiesPage() {
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const properties = useMemo(
    () =>
      curatedProperties.filter(
        (p) => !q || p.key.includes(q) || p.label.toLowerCase().includes(q) || p.qname.toLowerCase().includes(q),
      ),
    [q],
  );
  const units = useMemo(
    () =>
      curatedUnits.filter(
        (u) => !q || u.symbol.toLowerCase().includes(q) || u.label.toLowerCase().includes(q),
      ),
    [q],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Properties &amp; units</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Every spec property you can author, and the EMMO class it becomes.
          You type <code className="text-sm">nominal_capacity</code>; the world
          reads <code className="text-sm">emmo:NominalCapacity</code>. No
          ontology expertise required — the mapping is curated for you.
        </p>
        <p className="mt-3 text-sm text-ink-faint">
          {curatedProperties.length} curated properties · {curatedUnits.length} units ·
          generated from the canonical mapping tables, drift-checked in CI.
          Same data as <code className="text-xs">battinfo properties show</code>.
        </p>
      </header>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search properties and units — try “capacity”, “Wh”, or “impedance”…"
        className="mt-8 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
      />

      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">
          Properties ({properties.length})
        </h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="px-4 py-3">You write</th>
                <th className="px-4 py-3">EMMO class</th>
                <th className="px-4 py-3">IRI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {properties.map((p) => (
                <tr key={p.key} className="bg-white">
                  <td className="px-4 py-2.5 font-mono text-xs text-ink">{p.key}</td>
                  <td className="px-4 py-2.5 text-ink">{p.qname || p.label}</td>
                  <td className="px-4 py-2.5">
                    <a
                      href={p.iri}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-xs text-brand-600 hover:text-brand-700"
                    >
                      {p.iri.replace("https://w3id.org/", "w3id.org/")}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-faint">
          Units ({units.length})
        </h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="px-4 py-3">You write</th>
                <th className="px-4 py-3">EMMO unit</th>
                <th className="px-4 py-3">IRI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {units.map((u) => (
                <tr key={u.symbol} className="bg-white">
                  <td className="px-4 py-2.5 font-mono text-xs text-ink">{u.symbol}</td>
                  <td className="px-4 py-2.5 text-ink">{u.label}</td>
                  <td className="px-4 py-2.5">
                    <a
                      href={u.iri}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-xs text-brand-600 hover:text-brand-700"
                    >
                      {u.iri.replace("https://w3id.org/", "w3id.org/")}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-12 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-ink">Use them in a record</h2>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Any property above can go straight into a cell spec —{" "}
          <code className="text-xs">{`"nominal_capacity": { "value": 2.5, "unit": "Ah" }`}</code>{" "}
          — and the JSON-LD comes out EMMO-typed automatically.
        </p>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link href="/examples" className="font-semibold text-brand-600 hover:text-brand-700">
            See the JSON-LD it produces →
          </Link>
          <Link href="/publish" className="font-semibold text-brand-600 hover:text-brand-700">
            Publish your data →
          </Link>
          <a
            href={site.emmo}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-brand-600 hover:text-brand-700"
          >
            EMMO domain-battery →
          </a>
        </div>
      </section>
    </div>
  );
}

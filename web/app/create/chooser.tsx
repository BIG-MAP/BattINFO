"use client";

// Stage one: which kind of record. A file answers that question by itself, so
// opening one comes first and looks different from the grid below it.
//
// The grid is in DISCRIMINATORS order, which is battinfo.entities.ENTITY_KINDS
// order: the provenance chain first (cell spec, cell, test spec, test,
// dataset), then the components a cell is built from. That ordering is the
// package's, not an arrangement invented here.

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { read } from "./load";
import { FilePanel } from "./pick-file";
import { familyOf, RECORD_TYPES, slugOf, type Family } from "./types";
import { TEMPLATES } from "@/lib/templates.generated";
import { detectRecordType } from "@/lib/validate";

type Obj = Record<string, unknown>;

/** Encoded the way a link carries a record, so a file and a link from another
 *  tool arrive by the same route. */
async function toFragment(record: Obj): Promise<string> {
  const gz = await new Response(
    new Blob([JSON.stringify(record)]).stream().pipeThrough(new CompressionStream("gzip")),
  ).arrayBuffer();
  let binary = "";
  for (const byte of new Uint8Array(gz)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Which kind of record a reader wants is the first question here, and it is
// the one the model itself turns on. Asking it once, in the headings, saves
// asking it again at every row. The grouping is read from the schemas
// (types.ts's familyOf), never listed, so a record type added to the package
// lands in a group without this file being touched.
const GROUPS: { family: Family; heading: string; note: string }[] = [
  {
    family: "spec",
    heading: "Specifications",
    note: "The design: a cell model, an electrode design, a test protocol. One spec can describe any number of real things.",
  },
  {
    family: "instance",
    heading: "Instances",
    note: "What was actually built or run: a cell, the electrode in it, a test. Each needs the ID of the record it belongs to, usually its spec.",
  },
  {
    family: "other",
    heading: "Data and organizations",
    note: "Records other records point at: data files, parameter sets, and the manufacturers and labs behind any of them.",
  },
];

export function KindChooser() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const counts = new Map<string, number>();
  for (const template of TEMPLATES) {
    const key = detectRecordType(template.record as Obj);
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  async function openFile(file: File) {
    setError(null);
    try {
      const parsed = JSON.parse(await file.text()) as Obj;
      const key = detectRecordType(parsed);
      const type = key ? RECORD_TYPES.find((candidate) => candidate.key === key) : undefined;
      if (!type) {
        throw new Error("No record type found. A BattINFO record has a type key such as cell_spec at its top level.");
      }
      // Read it here as well, so a file the form cannot open says so on this
      // screen rather than the next one.
      await read(file, type);
      router.push(`/create/${slugOf(type)}#record=${await toFragment(parsed)}`);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  }

  return (
    <div className="mt-10">
      <FilePanel
        note="Open a BattINFO record saved earlier."
        onChoose={(file) => void openFile(file)}
        error={error}
      />

      {GROUPS.map((group) => {
        const kinds = RECORD_TYPES.filter((type) => familyOf(type) === group.family);
        if (!kinds.length) return null;
        return (
          <section key={group.heading} className="mt-8">
            <h2 className="text-sm font-semibold text-ink">{group.heading}</h2>
            <p className="mt-1 max-w-prose text-sm text-ink-muted">{group.note}</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {kinds.map((type) => {
                const templates = counts.get(type.key) ?? 0;
                return (
                  <Link
                    key={type.key}
                    href={`/create/${slugOf(type)}`}
                    className="flex items-baseline justify-between gap-3 rounded border border-border bg-surface px-4 py-3 transition-colors hover:border-brand-500"
                  >
                    <span className="text-sm font-medium text-ink">{type.label}</span>
                    {templates ? (
                      <span className="shrink-0 text-xs text-ink-faint">
                        {templates} template{templates === 1 ? "" : "s"}
                      </span>
                    ) : null}
                  </Link>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

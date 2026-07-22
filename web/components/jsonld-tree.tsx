"use client";

// Interactive tree for a JSON-LD node. Collapsible; @type shown as badges,
// @id as a short uid (full IRI on hover), w3id.org IRIs as links, terms shown
// compact with their absolute IRI on hover, and value/unit quantities on one
// line. Purely presentational, it renders whatever object it is handed (the
// raw document or the canonical framed view).

import { useState } from "react";

export interface TermMap {
  terms: Record<string, string>;
  prefixes: Record<string, string>;
}

/** Build a term/prefix -> absolute-IRI resolver from a merged @context. */
export function buildTermMap(context: Record<string, unknown>): TermMap {
  const prefixes: Record<string, string> = {};
  const terms: Record<string, string> = {};
  for (const [key, value] of Object.entries(context)) {
    if (key.startsWith("@")) continue;
    if (typeof value === "string" && (value.endsWith("#") || value.endsWith("/"))) {
      prefixes[key] = value;
    }
    const id = typeof value === "string" ? value : (value as Record<string, unknown>)?.["@id"];
    if (typeof id === "string") terms[key] = id;
  }
  const expand = (val: string): string => {
    const i = val.indexOf(":");
    if (i > 0) {
      const p = val.slice(0, i);
      if (prefixes[p]) return prefixes[p] + val.slice(i + 1);
    }
    return val;
  };
  for (const k of Object.keys(terms)) terms[k] = expand(terms[k]);
  return { terms, prefixes };
}

function resolveIri(token: string, map: TermMap): string | null {
  if (/^https?:\/\//.test(token)) return token;
  if (map.terms[token]) return map.terms[token];
  const i = token.indexOf(":");
  if (i > 0) {
    const p = token.slice(0, i);
    if (map.prefixes[p]) return map.prefixes[p] + token.slice(i + 1);
  }
  return null;
}

function shortLabel(token: string): string {
  const hash = token.lastIndexOf("#");
  const slash = token.lastIndexOf("/");
  const cut = Math.max(hash, slash);
  if (/^https?:\/\//.test(token) && cut >= 0) return token.slice(cut + 1);
  return token;
}

function isW3id(iri: string): boolean {
  return /^https?:\/\/w3id\.org\//.test(iri) || /^https?:\/\/(schema\.org|purl\.org)\//.test(iri);
}

function IriValue({ iri }: { iri: string }) {
  if (isW3id(iri)) {
    return (
      <a
        href={iri}
        target="_blank"
        rel="noreferrer"
        title={iri}
        className="font-mono text-xs text-brandtext underline decoration-dotted hover:text-brandtext"
      >
        {shortLabel(iri)}
      </a>
    );
  }
  return (
    <span title={iri} className="font-mono text-xs text-ink-muted">
      {shortLabel(iri)}
    </span>
  );
}

function TypeBadges({ value, map }: { value: unknown; map: TermMap }) {
  const types = Array.isArray(value) ? value : [value];
  return (
    <span className="inline-flex flex-wrap gap-1">
      {types.filter((t): t is string => typeof t === "string").map((t) => {
        const iri = resolveIri(t, map);
        return (
          <span
            key={t}
            title={iri ?? t}
            className="rounded bg-tint px-1.5 py-0.5 font-mono text-[10px] font-semibold text-brandtext"
          >
            {shortLabel(t)}
          </span>
        );
      })}
    </span>
  );
}

function TermKey({ term, map }: { term: string; map: TermMap }) {
  const iri = resolveIri(term, map);
  return (
    <span title={iri ?? undefined} className="mt-[1px] shrink-0 font-mono text-xs text-ink-muted">
      {term}
    </span>
  );
}

// A property node that is really a { value, unit } quantity -> render inline.
function quantityLine(node: Record<string, unknown>): { value: string; unit: string | null } | null {
  const part = node["hasNumericalPart"] as Record<string, unknown> | undefined;
  let value: unknown;
  if (part && typeof part === "object") value = part["hasNumberValue"] ?? part["hasNumericalValue"];
  if (value === undefined) value = node["value"] ?? node["schema:value"];
  if (value === undefined) return null;
  const rawUnit = node["hasMeasurementUnit"] ?? node["unit"];
  const unit = typeof rawUnit === "string" ? shortLabel(rawUnit) : null;
  return { value: String(value), unit };
}

function prefLabel(node: Record<string, unknown>): string | null {
  const p = node["skos:prefLabel"] ?? node["prefLabel"];
  return typeof p === "string" ? p : null;
}

function Primitive({ value }: { value: unknown }) {
  if (typeof value === "string" && /^https?:\/\//.test(value)) return <IriValue iri={value} />;
  if (typeof value === "string") return <span className="text-sm text-ink">{value}</span>;
  if (typeof value === "number" || typeof value === "boolean")
    return <span className="font-mono text-sm text-info">{String(value)}</span>;
  if (value === null) return <span className="font-mono text-sm text-ink-faint">null</span>;
  return <span className="text-sm text-ink">{String(value)}</span>;
}

// A fixed-width slot so keys line up whether or not a row has a disclosure caret.
function Caret({ open }: { open?: boolean }) {
  return (
    <span className="mt-[3px] w-3 shrink-0 select-none text-center font-mono text-[10px] leading-none text-ink-faint">
      {open === undefined ? "" : open ? "▾" : "▸"}
    </span>
  );
}

const ROW = "flex items-start gap-2 rounded-md px-1.5 py-1 hover:bg-tint/40";

function NodeRow({ termKey, value, map, depth }: { termKey: string; value: unknown; map: TermMap; depth: number }) {
  const isObject = value !== null && typeof value === "object";
  const [open, setOpen] = useState(depth < 2);

  if (!isObject) {
    return (
      <div className={ROW}>
        <Caret />
        <TermKey term={termKey} map={map} />
        <Primitive value={value} />
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const obj = isArray ? null : (value as Record<string, unknown>);
  const quantity = obj ? quantityLine(obj) : null;
  const label = obj ? prefLabel(obj) : null;
  const count = isArray ? (value as unknown[]).length : Object.keys(obj as object).length;

  return (
    <div>
      <button onClick={() => setOpen((o) => !o)} className={`${ROW} w-full text-left`}>
        <Caret open={open} />
        <TermKey term={termKey} map={map} />
        {obj && "@type" in obj ? <TypeBadges value={obj["@type"]} map={map} /> : null}
        {label ? <span className="text-xs text-ink-muted">{label}</span> : null}
        {quantity ? (
          <span className="font-mono text-sm text-ink">
            {quantity.value}
            {quantity.unit ? <span className="text-ink-muted"> {quantity.unit}</span> : null}
          </span>
        ) : (
          <span className="text-xs text-ink-faint">{isArray ? `${count} items` : `${count} fields`}</span>
        )}
      </button>
      {open ? (
        <div className="ml-[10px] border-l border-border/60 pl-2">
          <TreeChildren value={value} map={map} depth={depth + 1} />
        </div>
      ) : null}
    </div>
  );
}

function TreeChildren({ value, map, depth }: { value: unknown; map: TermMap; depth: number }) {
  if (Array.isArray(value)) {
    return (
      <>
        {value.map((item, i) => (
          <NodeRow key={i} termKey={`${i + 1}.`} value={item} map={map} depth={depth} />
        ))}
      </>
    );
  }
  const obj = value as Record<string, unknown>;
  return (
    <>
      {Object.entries(obj).map(([key, v]) => {
        if (key === "@type") return null; // rendered as badges in the parent row
        if (key === "@context") return null; // the context is not part of the data
        // @id/id is shown in the root header (depth 0); render it inline when nested.
        if ((key === "@id" || key === "id") && depth === 0) return null;
        if (key === "@id" || key === "id") {
          return (
            <div key={key} className={ROW}>
              <Caret />
              <span className="font-mono text-xs text-ink-muted">{key}</span>
              {typeof v === "string" ? <IriValue iri={v} /> : <Primitive value={v} />}
            </div>
          );
        }
        return <NodeRow key={key} termKey={key} value={v} map={map} depth={depth} />;
      })}
    </>
  );
}

export function JsonLdTree({ data, context }: { data: unknown; context: Record<string, unknown> }) {
  const map = buildTermMap(context);
  const root = data && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>) : null;
  const rootId = root ? root["@id"] ?? root["id"] : undefined;
  return (
    <div className="max-h-[34rem] overflow-auto rounded-xl border border-border bg-surface p-3 text-sm">
      {root && (root["@type"] || rootId) ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 border-b border-border pb-2">
          {root["@type"] ? <TypeBadges value={root["@type"]} map={map} /> : null}
          {typeof rootId === "string" ? <IriValue iri={rootId} /> : null}
        </div>
      ) : null}
      <TreeChildren value={data} map={map} depth={0} />
    </div>
  );
}

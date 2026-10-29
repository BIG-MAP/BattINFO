"use client";

// Everything on the Create page that needs the browser, in the order it is
// asked for:
//
//   /create            which kind of record       (app/create/chooser.tsx)
//   /create/<type>     what goes in it            (start.tsx)
//   /create/<type>     the record                 (here)
//
// Each question gets the screen to itself until it is answered. The kind
// needs no chrome once it is settled: the tree's outermost branch is the
// record's own key, which says it better than a label would.
//
// Nothing is stored. A draft lives for as long as the page is open, and
// leaving with work in it says so; to carry on another day, download the
// record and open it again. A half-written record quietly outliving the visit
// that made it was a surprise, not a feature -- and keeping it in step with
// what is on screen was the source of more than one bug.

import { useEffect, useMemo, useState } from "react";

import { ObjectNode } from "./node";
import {
  NEGATIVE_BASES,
  NEGATIVE_LIST,
  POSITIVE_BASES,
  POSITIVE_LIST,
  PROPERTY_KEYS,
  PROPERTY_LIST,
  UNIT_LIST,
  UNIT_SYMBOLS,
} from "./vocab";
import { HowToStart } from "./start";
import { BackLink } from "./pick-file";
import { asDraft, findingsFor, readFragment, type Loaded } from "./load";
import { notAuthored, slugOf, typeForSlug, type RecordType } from "./types";
import { validateRecordAs } from "@/lib/validate";

type Obj = Record<string, unknown>;

// Said in the confirm box, so the reason to think twice is the validator's own.
function notValidBecause(errors: { path: string; message: string }[]): string {
  const seen = new Map(errors.map((issue) => [issue.path, issue.message]));
  const shown = [...seen].slice(0, 6).map(([path, message]) => `  • ${path} — ${message}`);
  const rest = seen.size - shown.length;
  return [
    "This record is not valid yet:",
    "",
    ...shown,
    ...(rest > 0 ? [`  … and ${rest} more`] : []),
    "",
    "Download it anyway?",
  ].join("\n");
}

// Drop what the user has not filled in. An empty box means "not stated", and a
// record should say nothing rather than say "". false and 0 are real answers
// and survive.
function prune(value: unknown): unknown {
  if (Array.isArray(value)) {
    const items = value.map(prune).filter((item) => item !== undefined);
    return items.length ? items : undefined;
  }
  if (value !== null && typeof value === "object") {
    const out: Obj = {};
    for (const [key, item] of Object.entries(value)) {
      const kept = prune(item);
      if (kept !== undefined) out[key] = kept;
    }
    return Object.keys(out).length ? out : undefined;
  }
  return value === "" || value === null ? undefined : value;
}

function save(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  // Firefox will not act on a detached anchor, and aborts a download whose
  // object URL is revoked in the same task.
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// The slug crosses the boundary, not the record type: a RecordType carries its
// resolved schema, and serialising that would inline tens of kilobytes of
// JSON Schema into the HTML for the client to parse again. The slug is five
// characters and the client already has the schemas.
// The page header arrives as `children`: it is server-rendered markup handed
// through this client component, so the title is still in the HTML while the
// way back above it can be a button that knows whether there is a record to
// discard.
export default function CreateForm({ slug, children }: { slug: string; children: React.ReactNode }) {
  const type = typeForSlug(slug);
  if (!type) return null; // the route has already answered 404 for this
  return (
    <Stages key={type.key} type={type}>
      {children}
    </Stages>
  );
}

function Stages({ type, children }: { type: RecordType; children: React.ReactNode }) {
  // Null until the second question is answered. There is no form before then,
  // so there is nothing to render behind the question.
  const [begun, setBegun] = useState<Loaded | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);

  // A record handed over in the link answers both questions at once: another
  // tool chose the kind by linking here and supplied the contents.
  useEffect(() => {
    let cancelled = false;
    async function fromLink() {
      try {
        const linked = await readFragment(window.location.hash, type);
        if (cancelled) return;
        if (!linked) {
          setLinkError(null);
          return;
        }
        history.replaceState(null, "", window.location.pathname + window.location.search);
        setLinkError(null);
        setBegun(linked);
      } catch (problem) {
        // A link nobody can read is not a reason to withhold the page: the
        // chooser below is still offered, under a line saying what went wrong.
        if (!cancelled) setLinkError(problem instanceof Error ? problem.message : String(problem));
      }
    }
    const again = () => void fromLink();
    window.addEventListener("hashchange", again);
    void fromLink();
    return () => {
      cancelled = true;
      window.removeEventListener("hashchange", again);
    };
  }, [type]);

  return (
    <>
      {/* Above the title, where a way back belongs. It asks only once there
          is a record to lose. */}
      <BackLink
        href="/create"
        onNavigate={(event) => {
          if (begun && !window.confirm("Discard this record? It is not saved anywhere.")) {
            event.preventDefault();
          }
        }}
      >
        Back to Create
      </BackLink>
      {children}
      {!begun && linkError ? <p className="mt-6 text-sm text-error">{linkError}</p> : null}
      {begun ? <Record type={type} begun={begun} /> : <HowToStart type={type} onBegin={setBegun} />}
    </>
  );
}

function Record({ type, begun }: { type: RecordType; begun: Loaded }) {
  const [draft, setDraft] = useState<Obj>(() => asDraft(begun.record, type));

  const record = useMemo(() => (prune(draft) ?? {}) as Obj, [draft]);
  const result = useMemo(() => validateRecordAs(JSON.stringify(record), type.key), [record, type.key]);

  // The identity the library derives at save time. The schemas require an `id`
  // (and a dataset's `identifier`), so a new draft that rightly omits one is
  // still reported as missing it. This is the only place the form sets the
  // validator's verdict aside, and it is set aside once, here: the form shows
  // no row for these, so a count that included them was a problem nobody could
  // find. See findingsFor for exactly what is excused.
  const findings = useMemo(() => findingsFor(result.issues, type), [result, type]);

  // Those findings keyed by the dotted path they are reported at, so each row
  // in the tree can look up what is wrong with itself.
  const issues = useMemo(() => {
    const byPath: Map<string, string[]> = new Map();
    for (const issue of findings) {
      byPath.set(issue.path, [...(byPath.get(issue.path) ?? []), issue.message]);
    }
    return byPath;
  }, [findings]);

  const outstanding = findings.filter((issue) => issue.severity === "error");

  // A record that does not validate is not worth handing on, so the download
  // waits for it rather than producing a file someone else has to debug.
  // Counted by distinct path: one unsatisfied `anyOf` raises an error per
  // branch, and "13 fields" for a single missing unit would be a lie.
  const blocked = outstanding.length > 0;
  const stuck = new Set(outstanding.map((issue) => issue.path)).size;

  // Nothing is stored, so closing the tab is the end of it. The browser's own
  // warning is the only thing standing between a half-written record and a
  // stray reload.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  function downloadRecord() {
    if (blocked && !window.confirm(notValidBecause(outstanding))) return;
    save(`${slugOf(type)}.json`, "application/json", JSON.stringify(record, null, 2));
  }

  return (
    <>
      {/* The toolbar follows the record down: how it is doing, how to take it
          away and how to abandon it are wanted at the bottom of a long form as
          much as at the top. Pulled out to the container's edges so the
          backdrop covers the full width as rows pass behind it, and parked at
          `top-16` under the site header, which is itself sticky and four rem
          tall -- at top-0 it docked behind that and looked like it had simply
          scrolled away. */}
      <div className="sticky top-16 z-30 -mx-4 mt-8 border-b border-border bg-paper px-4 pb-3 pt-3 sm:-mx-6 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="flex-1" />

          <p className={`flex items-center gap-1.5 text-sm ${blocked ? "text-warning" : "text-volt-400"}`}>
            {blocked ? null : (
              <svg viewBox="0 0 16 16" aria-hidden className="w-3.5">
                <path d="M3.5 8.5l3 3 6-6.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            {blocked ? `${stuck} field${stuck === 1 ? "" : "s"} to fill` : "valid draft"}
          </p>
          <button
            type="button"
            onClick={downloadRecord}
            title="Download the record as it stands. Open it here again later to carry on."
            className="shrink-0 rounded bg-brand-500 px-3 py-1 text-sm font-medium text-white hover:bg-brand-600"
          >
            Download BattINFO JSON
          </button>
        </div>

        {/* The dropped fields stay: that is something that happened to the
            reader's own file, not a note about how the library behaves. */}
        {begun.removed.length ? (
          <p className="mt-2 text-xs text-warning">
            Dropped {begun.removed.length} field{begun.removed.length === 1 ? "" : "s"} not defined by the
            schemas: {begun.removed.slice(0, 6).join(", ")}
            {begun.removed.length > 6 ? ", …" : ""}
          </p>
        ) : null}
      </div>

      <div className="mt-6 grid gap-8 xl:grid-cols-12">
        <section className="xl:col-span-7">
          <ObjectNode
            loc={type.root}
            value={draft}
            onChange={setDraft}
            issues={issues}
            omit={notAuthored(type)}
          />
        </section>

        {/* Sticks below both sticky bars -- the site header (4rem) and the
            toolbar (3.4rem) -- and is as tall as what is left beneath them.
            Capped at 75vh it ended well short of the fold while the page kept
            scrolling past it. */}
        <section className="xl:col-span-5 xl:sticky xl:top-[7.8rem] xl:self-start">
          <div className="flex flex-col overflow-hidden rounded border border-border xl:max-h-[calc(100vh-8.6rem)]">
            <h2 className="shrink-0 border-b border-border bg-ink/[0.04] px-3 py-2 text-xs font-medium text-ink-faint">
              BattINFO JSON
            </h2>
            <pre className="min-h-0 flex-1 overflow-auto bg-surface p-3 text-xs leading-relaxed text-ink">
              {JSON.stringify(record, null, 2)}
            </pre>
          </div>
        </section>
      </div>

      <datalist id={UNIT_LIST}>
        {UNIT_SYMBOLS.map((unit) => (
          <option key={unit} value={unit} />
        ))}
      </datalist>
      <datalist id={PROPERTY_LIST}>
        {PROPERTY_KEYS.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>
      <datalist id={POSITIVE_LIST}>
        {POSITIVE_BASES.map((basis) => (
          <option key={basis} value={basis} />
        ))}
      </datalist>
      <datalist id={NEGATIVE_LIST}>
        {NEGATIVE_BASES.map((basis) => (
          <option key={basis} value={basis} />
        ))}
      </datalist>
    </>
  );
}

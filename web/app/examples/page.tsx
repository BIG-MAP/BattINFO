import type { Metadata } from "next";
import Link from "next/link";
import { type CodeTab, CodeTabs } from "@/components/code-tabs";
import { showcase } from "@/lib/showcase.generated";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Examples — describe your thing",
  description:
    "Materials, electrodes, electrolytes, cells, tests, datasets — real BattINFO authoring code for each, with the record and JSON-LD it produces. Every snippet is executed against the current library.",
};

/**
 * The showcase: for each thing you can describe, the literal source of a
 * snippet in scripts/gen_web_examples.py and the record executing it
 * produced, in a Python / JSON / JSON-LD tab set. Drift-checked by the test
 * suite — nothing here is illustrative.
 */
export default function ExamplesPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">
          Describe your thing
        </h1>
        <p className="mt-4 text-lg text-ink-muted">
          Whatever is on your bench — a material, an electrode, a cell, a test,
          the data it produced — there is a record for it. Each example below
          is real authoring code and the record it produces, executed against
          the current library and kept in sync by the test suite.
        </p>
      </header>

      <nav className="mt-8 flex flex-wrap gap-2">
        {showcase.map((entry) => (
          <a
            key={entry.slug}
            href={`#${entry.slug}`}
            className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700 hover:bg-brand-100"
          >
            {entry.title}
          </a>
        ))}
      </nav>

      {showcase.map((entry) => {
        const tabs: CodeTab[] = [
          {
            label: "Python",
            blockLabel: "you write",
            code: entry.code,
          },
          {
            label: "JSON",
            blockLabel: `${entry.slug}.json — the validated record`,
            code: JSON.stringify(entry.record, null, 2),
          },
        ];
        if (entry.jsonld) {
          tabs.push({
            label: "JSON-LD",
            blockLabel: `${entry.slug}.jsonld — EMMO Linked Data`,
            code: JSON.stringify(entry.jsonld, null, 2),
            extra: (
              <div className="flex flex-wrap gap-4 text-xs font-semibold">
                <a
                  href={`https://json-ld.org/playground/#startTab=tab-expanded&json-ld=${encodeURIComponent(`${site.url}/jsonld/showcase-${entry.slug}.jsonld`)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-600 hover:text-brand-700"
                >
                  Open in the JSON-LD Playground →
                </a>
                <a
                  href={`/jsonld/showcase-${entry.slug}.jsonld`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-ink-faint hover:text-ink"
                >
                  Raw JSON-LD
                </a>
              </div>
            ),
          });
        }
        return (
          <section key={entry.slug} className="mt-14 scroll-mt-24" id={entry.slug}>
            <h2 className="text-2xl font-semibold tracking-tight text-ink">
              {entry.title}
            </h2>
            <p className="mt-2 max-w-prose text-sm text-ink-muted">{entry.tagline}</p>
            <div className="mt-5">
              <CodeTabs tabs={tabs} />
            </div>
          </section>
        );
      })}

      <div className="mt-16 flex flex-wrap gap-4 text-sm">
        <Link href="/validate" className="font-semibold text-brand-600 hover:text-brand-700">
          Validate your own record →
        </Link>
        <Link href="/publish" className="font-semibold text-brand-600 hover:text-brand-700">
          Publish your data →
        </Link>
      </div>
    </div>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { SectionHeading } from "@/components/section-heading";
import { publishJourney, provenanceChain } from "@/lib/content";
import { installSnippet } from "@/lib/examples";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Publish your data — BattINFO",
  description:
    "The exact procedure for turning raw cycler exports into validated, citable, machine-readable battery records: convert, identify, link, save, publish.",
};

/**
 * The centerpiece page: the publishing procedure, stage by stage. Each stage
 * shows the exact code, what it produces on disk, and why the stage exists.
 * The code lines are asserted against ws.quickstart() by the test suite
 * (tests/test_web_snippets.py), so this page cannot drift from the library.
 */
export default function PublishPage() {
  return (
    <>
      <section className="border-b border-border bg-gradient-to-b from-brand-50/60 to-white">
        <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6">
          <SectionHeading
            kicker="The procedure"
            title="From cycler export to citable dataset — five stages."
          />
          <p className="mt-4 max-w-prose text-lg text-ink-muted">
            You bring a folder of instrument files. BattINFO walks them through
            five stages, each one checkable before the next. At the end you have
            validated records with permanent identifiers, a DOI you can put in a
            paper, and data the whole field can find and read.
          </p>
          <div className="mt-6 rounded-lg border border-border bg-white px-4 py-3">
            <p className="font-mono text-sm text-brand-700">
              raw files → BDF tables → {provenanceChain} → JSON-LD → DOI + registry
            </p>
          </div>
          <div className="mt-6">
            <CodeBlock label="setup (once)" code={installSnippet} />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-4xl px-4 py-14 sm:px-6">
        <ol className="space-y-12">
          {publishJourney.map((stage, i) => (
            <li key={stage.stage} className="relative">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-brand-600 font-mono text-sm font-bold text-white">
                  {i + 1}
                </span>
                <h2 className="text-xl font-semibold text-ink">{stage.stage}</h2>
                <code className="ml-1 hidden rounded bg-tint px-2 py-0.5 text-xs text-brand-700 sm:inline">
                  {stage.verb}
                </code>
              </div>
              <div className="mt-4 grid gap-6 lg:grid-cols-2">
                <div>
                  <CodeBlock label="python" code={stage.code} />
                </div>
                <div className="space-y-3 text-sm leading-relaxed">
                  <p>
                    <span className="font-semibold text-ink">You get: </span>
                    <span className="text-ink-muted">{stage.produces}</span>
                  </p>
                  <p>
                    <span className="font-semibold text-ink">Why this stage exists: </span>
                    <span className="text-ink-muted">{stage.why}</span>
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-border bg-surface">
        <div className="mx-auto max-w-4xl px-4 py-14 sm:px-6">
          <SectionHeading kicker="Before you publish" title="Check your record here, in the browser." />
          <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
            Paste any record into the validator to see exactly what the library
            and the registry will say about it — same schemas, same verdict. Or
            explore a finished example first to see where you are heading.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/validate"
              className="rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700"
            >
              Validate a record
            </Link>
            <Link
              href="/examples"
              className="rounded-lg border border-border bg-white px-5 py-3 text-sm font-semibold text-ink transition hover:bg-tint"
            >
              See a worked example
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-4xl px-4 py-14 sm:px-6">
        <SectionHeading kicker="Go deeper" title="The full tutorial and reference live in the docs." />
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
          This page is the map. The step-by-step tutorial — with a sample
          dataset, validation output, and the Zenodo sandbox — plus the complete
          Python API, CLI, and schema reference, live in the developer
          documentation.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href={site.reference}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-border bg-white px-5 py-3 text-sm font-semibold text-ink transition hover:bg-tint"
          >
            Developer reference →
          </a>
          <a
            href={site.genome}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-border bg-white px-5 py-3 text-sm font-semibold text-ink transition hover:bg-tint"
          >
            See published data on Battery Genome →
          </a>
        </div>
      </section>
    </>
  );
}

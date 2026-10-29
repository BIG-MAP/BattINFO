// The Create page's shell: a server component, so the heading, the
// explanation and the tab title are in the HTML the browser gets. The form
// underneath needs the browser and arrives with the bundle; everything that
// can be read before then is here, and no longer waits for it.
//
// Prerendered for all twenty-two record types (generateStaticParams), and
// `dynamicParams = false` makes an unknown slug a static 404 rather than a
// function call that ends in one.

import type { Metadata } from "next";
import { notFound } from "next/navigation";
import CreateForm from "../form";
import { BetaBadge } from "../ui";
import { NO_NATURAL_KEY, RECORD_TYPES, slugOf, typeForSlug } from "../types";

export const dynamicParams = false;

export function generateStaticParams() {
  return RECORD_TYPES.map((type) => ({ type: slugOf(type) }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ type: string }>;
}): Promise<Metadata> {
  const type = typeForSlug((await params).type);
  const what = type ? type.label.toLowerCase() : "record";
  return {
    title: `Create a ${what} (beta)`,
    description:
      `Build a canonical BattINFO ${what} in the browser. Every field, option and constraint comes from ` +
      "the published JSON Schemas, so a draft cannot drift from the package.",
  };
}

export default async function CreatePage({ params }: { params: Promise<{ type: string }> }) {
  const slug = (await params).type;
  const type = typeForSlug(slug);
  if (!type) notFound();

  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      {/* The header is handed to the client as children, so it stays in the
          server HTML while the way back above it can ask before discarding a
          record. The type is settled by the time anyone is here, so the
          heading states it rather than offering it again. */}
      <CreateForm slug={slug}>
        <header className="mt-4 max-w-prose">
          <h1 className="text-4xl font-bold tracking-tight text-ink">
            Create a {type.label.toLowerCase()}
          </h1>
          <p className="mt-4 text-ink-muted">
            Save the download with{" "}
            <code className="rounded bg-paper-deep px-1 py-0.5 font-mono text-sm">
              battinfo save record --input {slug}.json --source-root {"<folder>"}
            </code>
          </p>
          {NO_NATURAL_KEY.includes(type.key) ? (
            <p className="mt-2 text-ink-muted">
              The package cannot derive an id for a {type.label.toLowerCase()}, so create new ones in Python
              with <code className="font-mono text-sm">uid=</code>. One opened here keeps its own.
            </p>
          ) : null}
          <div className="mt-4">
            <BetaBadge />
          </div>
        </header>
      </CreateForm>
    </div>
  );
}

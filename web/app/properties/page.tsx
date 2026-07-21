import type { Metadata } from "next";
import Link from "next/link";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Properties & units",
  description:
    "The full property & unit reference, every authoring key and unit symbol with its EMMO IRI, lives in the BattINFO documentation.",
};

/**
 * Pointer page: the property/unit tables are reference material and moved to
 * the documentation (generated from the canonical mapping tables there).
 * The URL stays alive because it has been linked externally.
 */
export default function PropertiesPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
      <h1 className="text-4xl font-bold tracking-tight text-ink">
        Properties &amp; units
      </h1>
      <p className="mt-4 text-lg text-ink-muted">
        The full reference, every key you can write in{" "}
        <code className="rounded bg-paper-deep px-1.5 py-0.5 font-mono text-sm">
          properties=&#123;...&#125;
        </code>{" "}
        and every unit symbol, each linked to the EMMO class or unit IRI it
        becomes in JSON-LD, lives in the documentation, generated straight
        from the canonical mapping tables.
      </p>
      <div className="mt-8 flex flex-wrap gap-4">
        <a
          href={`${site.reference}/pages/property-reference.html`}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg bg-primary px-5 py-2.5 font-semibold text-primary-fg hover:opacity-90"
        >
          Open the property &amp; unit reference →
        </a>
        <Link
          href="/examples"
          className="rounded-lg border border-line px-5 py-2.5 font-semibold text-ink hover:border-brand-300"
        >
          See them used in examples
        </Link>
      </div>
      <p className="mt-6 text-sm text-ink-faint">
        Installed? <code className="font-mono">battinfo properties show</code>{" "}
        prints the same tables in your terminal.
      </p>
    </div>
  );
}

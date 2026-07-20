import type { Metadata } from "next";
import Link from "next/link";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "About BattINFO",
  description:
    "Where BattINFO comes from, what it is for, and the ecosystem it belongs to, the EMMO battery ontology, the Battery Genome, and open battery-data infrastructure.",
};

const ecosystem = [
  {
    name: "EMMO domain-battery",
    href: site.emmo,
    role: "The ontology itself: the formal EMMO-based vocabulary of battery concepts that BattINFO implements and extends.",
  },
  {
    name: "Battery Genome",
    href: site.genome,
    role: "The open platform where published BattINFO records become browsable cell pages, linked datasets, and federated profiles.",
  },
  {
    name: "battinfo-records",
    href: "https://github.com/BIG-MAP/battinfo-records",
    role: "The canonical record library: curated cell specs and organizations that anchor the registry.",
  },
  {
    name: "BIG-MAP",
    href: "https://www.big-map.eu/",
    role: "The Battery 2030+ large-scale European research project this work grew out of.",
  },
  {
    name: "Battery Data Alliance",
    href: "https://pypi.org/project/batterydf/",
    role: "Home of the Battery Data Format (BDF), the tidy tabular layer BattINFO converts raw cycler files into.",
  },
] as const;

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
      <h1 className="text-4xl font-bold tracking-tight text-ink">About BattINFO</h1>

      <section className="mt-8 space-y-4 text-ink-muted">
        <h2 className="text-2xl font-semibold tracking-tight text-ink">Mission</h2>
        <p>
          Battery R&amp;D runs on data that mostly cannot be reused: numbers
          locked in PDFs, spreadsheets with private column names, cycler
          exports whose meaning left the lab with the person who ran them.
          BattINFO&apos;s mission is to make battery data{" "}
          <strong className="text-ink">machine-readable, linked, and reusable</strong>,
          so that every cell, test, and dataset carries its own meaning and any
          tool or team can pick it up without asking.
        </p>
        <p>
          We did not invent our own world. We build on open standards (EMMO,
          JSON-LD, JSON Schema, schema.org, DCAT, PROV) and make them usable by
          someone with a datasheet and an afternoon.
        </p>
        <p>
          <Link href="/federation" className="font-semibold text-brand-600 hover:text-brand-700">
            Why linked, federated data changes what battery research can do →
          </Link>
        </p>
      </section>

      <section className="mt-12 space-y-4 text-ink-muted">
        <h2 className="text-2xl font-semibold tracking-tight text-ink">History</h2>
        <p>
          BattINFO began as an ontology: the <em>Battery INterFace Ontology</em>,
          developed in the European{" "}
          <a href="https://www.big-map.eu/" className="text-brand-600 hover:text-brand-700">
            BIG-MAP
          </a>{" "}
          project (part of the Battery 2030+ initiative) and now maintained as
          the{" "}
          <a href={site.emmo} className="text-brand-600 hover:text-brand-700">
            EMMO battery domain
          </a>
          . The ontology answered <em>what battery concepts mean</em>; what
          remained open was how a working scientist would actually use it.
        </p>
        <p>
          This project is that answer: the implementation layer that turns the
          ontology into everyday tools, canonical JSON records with schemas,
          a Python library and CLI, automatic JSON-LD with persistent{" "}
          <code className="rounded bg-paper-deep px-1 py-0.5 font-mono text-sm">
            w3id.org/battinfo/…
          </code>{" "}
          identifiers, and a publishing pipeline that ends in a citable DOI
          and a registry entry. It is open source (Apache-2.0) and developed
          in the open on{" "}
          <a href={site.github} className="text-brand-600 hover:text-brand-700">
            GitHub
          </a>
          .
        </p>
      </section>

      <section className="mt-12">
        <h2 className="text-2xl font-semibold tracking-tight text-ink">The ecosystem</h2>
        <p className="mt-3 text-ink-muted">
          BattINFO is one layer of a larger open battery-data stack:
        </p>
        <ul className="mt-5 space-y-4">
          {ecosystem.map((item) => (
            <li key={item.name} className="rounded-lg border border-line p-4">
              <a
                href={item.href}
                target="_blank"
                rel="noreferrer"
                className="font-semibold text-brand-600 hover:text-brand-700"
              >
                {item.name} →
              </a>
              <p className="mt-1 text-sm text-ink-muted">{item.role}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12 text-ink-muted">
        <h2 className="text-2xl font-semibold tracking-tight text-ink">Get involved</h2>
        <p className="mt-3">
          Publish a dataset, register a cell spec, report a rough edge, or
          bring your tool&apos;s format to the converter matrix, every record
          published makes the shared library more useful.{" "}
          <Link href="/publish" className="text-brand-600 hover:text-brand-700">
            Start with your own data
          </Link>
          , or open an issue on{" "}
          <a href={site.github} className="text-brand-600 hover:text-brand-700">
            GitHub
          </a>
          .
        </p>
      </section>
    </div>
  );
}

// The door to the Create page: which kind of record, asked before there is a
// form to answer it over. A server component, so the heading and the question
// are in the HTML and do not wait for a bundle; the chooser underneath needs
// the browser only to read a file someone drops on it.

import type { Metadata } from "next";
import Link from "next/link";
import { KindChooser } from "./chooser";
import { BetaBadge } from "./ui";

export const metadata: Metadata = {
  title: "Create a record (beta)",
  description:
    "Build a canonical BattINFO record in the browser. Every field, option and constraint comes from the published JSON Schemas, so a draft cannot drift from the package.",
};

export default function CreateIndex() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Create a record</h1>
        <p className="mt-4 text-lg text-ink-muted">
          Records can be written and edited with the{" "}
          <Link href="/docs#quickstart" className="font-semibold text-brandtext hover:text-brandtext">
            Python package
          </Link>{" "}
          or here in the browser. To publish one, download it and{" "}
          <Link href="/publish" className="font-semibold text-brandtext hover:text-brandtext">
            publish it with the package
          </Link>
          .
        </p>
        <div className="mt-4">
          <BetaBadge />
        </div>
      </header>

      <KindChooser />
    </div>
  );
}

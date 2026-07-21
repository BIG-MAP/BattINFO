import Link from "next/link";
import { footerNav, site } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
          <div className="col-span-2 md:col-span-1">
            <span className="text-lg font-semibold tracking-tight text-ink">
              Batt<span className="text-brandtext">INFO</span>
            </span>
            <p className="mt-2 max-w-xs text-sm text-ink-muted">
              The semantic data layer for battery technology. Built on{" "}
              <a href={site.emmo} className="underline hover:text-ink" target="_blank" rel="noreferrer">
                EMMO domain-battery
              </a>
              .
            </p>
          </div>

          {footerNav.map((col) => (
            <div key={col.heading}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{col.heading}</h3>
              <ul className="mt-3 space-y-2">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {"external" in link && link.external ? (
                      <a href={link.href} target="_blank" rel="noreferrer" className="text-sm text-ink-muted hover:text-ink">
                        {link.label}
                      </a>
                    ) : (
                      <Link href={link.href} className="text-sm text-ink-muted hover:text-ink">
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 flex flex-col gap-2 border-t border-border pt-6 text-xs text-ink-faint sm:flex-row sm:items-center sm:justify-between">
          <p>{site.license}</p>
          <p>
            IRIs resolve via{" "}
            <a href="https://w3id.org/battinfo/" className="underline hover:text-ink" target="_blank" rel="noreferrer">
              w3id.org/battinfo
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}

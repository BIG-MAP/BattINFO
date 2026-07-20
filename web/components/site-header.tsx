import Link from "next/link";
import { primaryNav, site } from "@/lib/site";
import { ThemeToggle } from "@/components/theme-toggle";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-surface/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center">
          {/* Canonical horizontal lockup from the brand pack (brand/assets/logo). */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo-horizontal.svg" alt="BattINFO" className="h-7 w-auto dark:brightness-0 dark:invert" />
        </Link>

        <nav className="flex items-center gap-1 sm:gap-2">
          {primaryNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-tint hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
          <ThemeToggle />
          <a
            href={site.github}
            target="_blank"
            rel="noreferrer"
            className="ml-1 rounded-md bg-ink-deep px-3 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}

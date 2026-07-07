"use client";

import { type ReactNode, useState } from "react";
import { CodeBlock } from "@/components/code-block";

export interface CodeTab {
  label: string;
  code: string;
  blockLabel?: string;
  /** Extra content rendered above the code block (e.g. playground links). */
  extra?: ReactNode;
}

/**
 * Tabbed code viewer (Python / JSON / JSON-LD), mirroring the tab-set on the
 * docs landing page. Long documents scroll inside the panel instead of
 * stretching the page.
 */
export function CodeTabs({ tabs }: { tabs: CodeTab[] }) {
  const [active, setActive] = useState(0);
  const tab = tabs[active];

  return (
    <div>
      <div className="flex gap-1 rounded-t-xl border border-b-0 border-border bg-paper px-2 pt-2">
        {tabs.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setActive(i)}
            className={
              i === active
                ? "rounded-t-lg border border-b-0 border-border bg-white px-4 py-2 text-sm font-semibold text-brand-700"
                : "rounded-t-lg px-4 py-2 text-sm font-medium text-ink-faint hover:text-ink"
            }
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="rounded-b-xl border border-t-0 border-border bg-white p-3">
        {tab.extra ? <div className="mb-3">{tab.extra}</div> : null}
        <div className="max-h-[28rem] overflow-y-auto rounded-xl">
          <CodeBlock label={tab.blockLabel ?? tab.label} code={tab.code} />
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";

interface CodeBlockProps {
  code: string;
  language?: string;
  label?: string;
}

export function CodeBlock({ code, language, label }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable, non-fatal */
    }
  }

  return (
    <div className="group relative overflow-hidden rounded-xl border border-border bg-code-bg">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="font-mono text-xs uppercase tracking-wider text-ink-faint">
          {label ?? language ?? "code"}
        </span>
        <button
          onClick={copy}
          className="rounded-md px-2 py-1 text-xs font-medium text-ink-muted transition hover:bg-tint hover:text-ink"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-sm leading-relaxed">
        <code className="font-mono text-code-fg">{code}</code>
      </pre>
    </div>
  );
}

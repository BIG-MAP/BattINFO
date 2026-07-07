"use client";

/**
 * The hero constellation: the provenance chain as a gently floating graph.
 * CellSpec → Cell → Test → Dataset, grounded by EMMO underneath. Pure SVG +
 * CSS keyframes (no dependencies); hover names each node's job, click
 * navigates. Colors come from the brand tokens via Tailwind's palette.
 */

const NODES = [
  { id: "cellspec", label: "CellSpec", hint: "The product datasheet, as data", href: "/examples#cell-spec", x: 90, y: 90, r: 34, accent: false },
  { id: "cell", label: "Cell", hint: "The physical cell on your bench", href: "/publish", x: 235, y: 60, r: 30, accent: false },
  { id: "test", label: "Test", hint: "What you did to it, linked forever", href: "/publish", x: 360, y: 130, r: 30, accent: false },
  { id: "dataset", label: "Dataset", hint: "What it produced — citable, with a DOI", href: "/publish", x: 300, y: 265, r: 34, accent: false },
  { id: "emmo", label: "EMMO", hint: "The shared ontology every record speaks", href: "/examples", x: 120, y: 250, r: 38, accent: true },
] as const;

const EDGES: [string, string, boolean][] = [
  ["cellspec", "cell", false],
  ["cell", "test", false],
  ["test", "dataset", false],
  ["emmo", "cellspec", true],
  ["emmo", "dataset", true],
  ["emmo", "test", true],
];

function node(id: string) {
  return NODES.find((n) => n.id === id)!;
}

export function Constellation() {
  return (
    <div className="relative select-none">
      <style>{`
        @keyframes bi-float-a { 0%,100% { transform: translate(0,0);} 50% { transform: translate(4px,-7px);} }
        @keyframes bi-float-b { 0%,100% { transform: translate(0,0);} 50% { transform: translate(-6px,5px);} }
        @keyframes bi-float-c { 0%,100% { transform: translate(0,0);} 50% { transform: translate(5px,6px);} }
        .bi-node { transition: filter .2s ease; }
        .bi-node:hover { filter: brightness(1.06) drop-shadow(0 4px 10px rgba(18,163,148,.35)); }
        .bi-node .bi-hint { opacity: 0; transition: opacity .18s ease; }
        .bi-node:hover .bi-hint { opacity: 1; }
        @media (prefers-reduced-motion: reduce) { .bi-drift { animation: none !important; } }
      `}</style>
      <svg viewBox="0 0 470 330" className="w-full" role="img" aria-label="The BattINFO provenance graph: CellSpec, Cell, Test, and Dataset records, grounded in the EMMO ontology">
        {/* edges */}
        {EDGES.map(([from, to, dashed]) => {
          const a = node(from);
          const b = node(to);
          return (
            <line
              key={`${from}-${to}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={dashed ? "#9cdcd3" : "#12a394"}
              strokeWidth={dashed ? 1.5 : 2.5}
              strokeDasharray={dashed ? "4 6" : undefined}
              strokeLinecap="round"
              opacity={dashed ? 0.8 : 0.9}
            />
          );
        })}
        {/* nodes */}
        {NODES.map((n, i) => (
          <g
            key={n.id}
            className="bi-drift"
            style={{
              animation: `bi-float-${["a", "b", "c"][i % 3]} ${7 + i * 1.3}s ease-in-out ${i * 0.9}s infinite`,
            }}
          >
            <a href={n.href} className="bi-node" aria-label={`${n.label}: ${n.hint}`}>
              <circle
                cx={n.x} cy={n.y} r={n.r}
                fill={n.accent ? "#102a43" : "#e4f4f1"}
                stroke={n.accent ? "#102a43" : "#12a394"}
                strokeWidth={2}
              />
              <text
                x={n.x} y={n.y + 5}
                textAnchor="middle"
                fontFamily="Plus Jakarta Sans, system-ui, sans-serif"
                fontSize={n.r > 32 ? 15 : 13}
                fontWeight={700}
                fill={n.accent ? "#ffffff" : "#0c7a6e"}
              >
                {n.label}
              </text>
              <g className="bi-hint">
                <rect
                  x={n.x - 108} y={n.y + n.r + 8} width={216} height={26} rx={6}
                  fill="#102a43" opacity={0.95}
                />
                <text
                  x={n.x} y={n.y + n.r + 25}
                  textAnchor="middle"
                  fontFamily="Plus Jakarta Sans, system-ui, sans-serif"
                  fontSize={11.5}
                  fill="#f3f2ee"
                >
                  {n.hint}
                </text>
              </g>
            </a>
          </g>
        ))}
      </svg>
      <p className="mt-2 text-center text-xs text-ink-faint">
        Every record knows what it describes, what touched it, and what it produced — hover, then click through.
      </p>
    </div>
  );
}

"use client";

// A small node-edge-node view of the document's linked-data structure: the
// record and the things it points at, with the relationship on each edge. It is
// deliberately shallow and aggregates large quantity lists — it shows how the
// entities connect, not every number (the Summary and Table do the numbers).

import { useMemo } from "react";

interface GNode {
  id: string;
  title: string;
  subtitle?: string;
  aggregate?: boolean;
  depth: number;
  x: number;
  y: number;
}

interface GEdge {
  from: string;
  to: string;
  label: string;
}

const MAX_DEPTH = 3;
const MAX_CHILDREN = 6;
const MAX_NODES = 48;

const NODE_W = 176;
const NODE_H = 50;
const COL_W = 250;
const V_GAP = 22;
const PAD = 16;

function short(token: string): string {
  if (/^https?:\/\//.test(token)) {
    const cut = Math.max(token.lastIndexOf("#"), token.lastIndexOf("/"));
    return cut >= 0 ? token.slice(cut + 1) : token;
  }
  const colon = token.indexOf(":");
  return colon > 0 ? token.slice(colon + 1) : token;
}

function typeList(node: Record<string, unknown>): string[] {
  const t = node["@type"];
  if (typeof t === "string") return [short(t)];
  if (Array.isArray(t)) return t.filter((x): x is string => typeof x === "string").map(short);
  return [];
}

function name(node: Record<string, unknown>): string | undefined {
  const n = node["name"] ?? node["schema:name"] ?? node["skos:prefLabel"];
  return typeof n === "string" ? n : undefined;
}

function edgeLabel(key: string): string {
  const local = short(key).replace(/^has/, "").replace(/([A-Z])/g, " $1").trim().toLowerCase();
  return local || short(key);
}

function build(root: Record<string, unknown>): { nodes: GNode[]; edges: GEdge[] } {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  let counter = 0;

  const addNode = (obj: Record<string, unknown>, depth: number): string => {
    const id = String(counter++);
    const types = typeList(obj);
    const nm = name(obj);
    const title = types[0] ?? nm ?? "node";
    const subtitle = nm && nm !== title ? nm : types.slice(1).join(", ") || undefined;
    nodes.push({ id, title, subtitle, depth, x: 0, y: 0 });
    return id;
  };

  const addAggregate = (title: string, depth: number): string => {
    const id = String(counter++);
    nodes.push({ id, title, aggregate: true, depth, x: 0, y: 0 });
    return id;
  };

  const expand = (obj: Record<string, unknown>, id: string, depth: number) => {
    if (depth >= MAX_DEPTH || nodes.length >= MAX_NODES) return;
    for (const [key, value] of Object.entries(obj)) {
      if (key.startsWith("@") || key === "skos:prefLabel" || key === "prefLabel") continue;
      if (key === "hasProperty") {
        const n = Array.isArray(value) ? value.length : value ? 1 : 0;
        if (n === 0) continue;
        const pid = addAggregate(`${n} propert${n === 1 ? "y" : "ies"}`, depth + 1);
        edges.push({ from: id, to: pid, label: "properties" });
        continue;
      }
      const items = Array.isArray(value) ? value : [value];
      const objs = items.filter((o): o is Record<string, unknown> => !!o && typeof o === "object");
      if (objs.length === 0) continue;
      objs.slice(0, MAX_CHILDREN).forEach((o) => {
        if (nodes.length >= MAX_NODES) return;
        const cid = addNode(o, depth + 1);
        edges.push({ from: id, to: cid, label: edgeLabel(key) });
        expand(o, cid, depth + 1);
      });
      if (objs.length > MAX_CHILDREN) {
        const mid = addAggregate(`+${objs.length - MAX_CHILDREN} more`, depth + 1);
        edges.push({ from: id, to: mid, label: edgeLabel(key) });
      }
    }
  };

  const rootId = addNode(root, 0);
  expand(root, rootId, 0);

  // Layered layout: one column per depth, nodes stacked and vertically centered.
  const byDepth = new Map<number, GNode[]>();
  for (const n of nodes) {
    const list = byDepth.get(n.depth) ?? [];
    list.push(n);
    byDepth.set(n.depth, list);
  }
  const tallest = Math.max(...[...byDepth.values()].map((l) => l.length));
  const colHeight = tallest * NODE_H + (tallest - 1) * V_GAP;
  for (const [depth, list] of byDepth) {
    const height = list.length * NODE_H + (list.length - 1) * V_GAP;
    const startY = PAD + (colHeight - height) / 2;
    list.forEach((n, i) => {
      n.x = PAD + depth * COL_W;
      n.y = startY + i * (NODE_H + V_GAP);
    });
  }
  return { nodes, edges };
}

export function JsonLdGraph({ framed }: { framed: Record<string, unknown> }) {
  const { nodes, edges } = useMemo(() => {
    const { ["@context"]: _c, ...rest } = framed;
    void _c;
    return build(rest);
  }, [framed]);

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const maxDepth = Math.max(...nodes.map((n) => n.depth));
  const width = PAD * 2 + maxDepth * COL_W + NODE_W;
  const height = PAD * 2 + (Math.max(...nodes.map((n) => n.y)) - PAD + NODE_H);

  return (
    <div className="overflow-auto rounded-xl border border-border bg-white p-2">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="min-w-full"
        role="img"
        aria-label="Graph of the document's entities and relationships"
      >
        {edges.map((e, i) => {
          const from = byId.get(e.from);
          const to = byId.get(e.to);
          if (!from || !to) return null;
          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          const labelW = e.label.length * 6.2 + 8;
          return (
            <g key={i}>
              <path
                d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                className="fill-none stroke-border"
                strokeWidth={1.5}
              />
              <rect x={mx - labelW / 2} y={(y1 + y2) / 2 - 9} width={labelW} height={16} rx={3} className="fill-white" />
              <text
                x={mx}
                y={(y1 + y2) / 2 + 3}
                textAnchor="middle"
                className="fill-ink-faint font-mono"
                style={{ fontSize: 10 }}
              >
                {e.label}
              </text>
            </g>
          );
        })}
        {nodes.map((n) => (
          <g key={n.id}>
            <rect
              x={n.x}
              y={n.y}
              width={NODE_W}
              height={NODE_H}
              rx={10}
              className={n.aggregate ? "fill-surface stroke-border" : n.depth === 0 ? "fill-brand-50 stroke-brand-300" : "fill-white stroke-border"}
              strokeWidth={1.5}
              strokeDasharray={n.aggregate ? "4 3" : undefined}
            />
            <text
              x={n.x + 12}
              y={n.subtitle ? n.y + 21 : n.y + 29}
              className={n.aggregate ? "fill-ink-muted italic" : "fill-ink font-semibold"}
              style={{ fontSize: 12 }}
            >
              {clip(n.title, 22)}
            </text>
            {n.subtitle ? (
              <text x={n.x + 12} y={n.y + 36} className="fill-ink-muted" style={{ fontSize: 10 }}>
                {clip(n.subtitle, 26)}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
    </div>
  );
}

function clip(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

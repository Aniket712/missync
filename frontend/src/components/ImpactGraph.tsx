import { Background, Controls, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { Analysis } from "../api";

type G = Analysis["graph"];

const ICON: Record<string, string> = { table: "▦", view: "◫", asset: "★", column: "│" };

function layout(g: G): { nodes: Node[]; edges: Edge[] } {
  const depth = new Map<string, number>();
  const incoming = new Map<string, string[]>();
  g.edges.forEach((e) => incoming.set(e.target, [...(incoming.get(e.target) ?? []), e.source]));
  const d = (id: string, seen: Set<string> = new Set()): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const ins = incoming.get(id) ?? [];
    const v = ins.length ? 1 + Math.max(...ins.map((i) => d(i, seen))) : 0;
    depth.set(id, v);
    return v;
  };
  g.nodes.forEach((n) => d(n.id));
  const colSize = new Map<number, number>();
  g.nodes.forEach((n) => colSize.set(depth.get(n.id) ?? 0, (colSize.get(depth.get(n.id) ?? 0) ?? 0) + 1));
  const rows = new Map<number, number>();
  const nodes: Node[] = g.nodes.map((n) => {
    const col = depth.get(n.id) ?? 0;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    const tone = n.changed ? "var(--high)" : n.impacted ? "var(--medium)" : "var(--line)";
    return {
      id: n.id,
      position: { x: col * 280, y: (row - ((colSize.get(col) ?? 1) - 1) / 2) * 96 },
      data: {
        label: (
          <div style={{ textAlign: "left", lineHeight: 1.25 }}>
            <div style={{ fontWeight: 600 }}>
              {ICON[n.type] ?? "•"} {n.label}
            </div>
            <div style={{ fontSize: 11, opacity: 0.75 }}>
              {n.changed ? "Changed" : n.impacted ? "Impacted" : n.type}
              {n.detail ? ` — ${n.detail}` : ""}
            </div>
          </div>
        ),
      },
      style: {
        width: 230,
        borderRadius: 10,
        padding: 8,
        border: `2px solid rgb(${tone})`,
        background: "rgb(var(--surface))",
        color: "rgb(var(--fg))",
        fontSize: 12,
      },
      draggable: false,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
  });
  const edges: Edge[] = g.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    animated: false,
    style: { stroke: "rgb(var(--muted))", strokeDasharray: e.complete ? undefined : "5 4" },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
  return { nodes, edges };
}

export default function ImpactGraph({ graph }: { graph: G }) {
  const { nodes, edges } = useMemo(() => layout(graph), [graph]);
  if (!graph.nodes.length) return <p className="text-sm text-muted">No objects to trace for this change.</p>;
  return (
    <div>
      {!graph.complete && (
        <div className="mb-2 rounded-lg border border-medium/40 bg-medium/10 p-2 text-sm text-medium" role="note">
          Lineage is incomplete — additional dependents may exist that Missync could not see. Dashed edges mark unresolved links.
        </div>
      )}
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Legend">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border-2 border-high" /> Changed by your SQL</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border-2 border-medium" /> Impacted (depends on a changed object)</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border-2 border-line" /> Related, not affected</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-muted" /> Unresolved link</span>
        <span>▦ table · ◫ view · ★ downstream asset</span>
      </div>
      <div className="h-[380px] overflow-hidden rounded-xl border border-line" aria-label="Impact graph">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false} proOptions={{ hideAttribution: true }}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <ul className="mt-3 grid gap-1 text-sm sm:grid-cols-2">
        {graph.nodes.map((n) => (
          <li key={n.id} className="text-muted">
            <span className="font-medium text-fg">{n.label}</span> · {n.changed ? "changed" : n.impacted ? "impacted" : n.type}
            {n.detail ? ` (${n.detail})` : ""}
          </li>
        ))}
      </ul>
      {graph.notes.map((n) => (
        <p key={n} className="mt-1 text-xs text-muted">
          {n}
        </p>
      ))}
    </div>
  );
}

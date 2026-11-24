"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface GradeStatusPoint {
  status: string;
  count: number;
}

function barColour(status: string) {
  if (status === "Draft") return "#8e4ec6";
  if (status === "Approved") return "#16a34a";
  if (status === "Pushed") return "#2563eb";
  return "#a3a3a3";
}

/**
 * Group-status chart for the assignment dashboard. Split into its own module so
 * the page can load recharts on demand instead of in the initial bundle.
 * Every series comes from the real submission rows - no synthetic values.
 */
export function GradeStatusChart({ data }: { data: GradeStatusPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="oklch(from var(--color-foreground) l c h / 0.07)"
          vertical={false}
        />
        <XAxis
          dataKey="status"
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "oklch(from var(--color-foreground) l c h / 0.45)",
          }}
        />
        <YAxis
          stroke="oklch(from var(--color-foreground) l c h / 0.3)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tick={{
            fontFamily: "var(--font-mono)",
            fill: "oklch(from var(--color-foreground) l c h / 0.45)",
          }}
          width={28}
          allowDecimals={false}
        />
        <Tooltip
          content={<GradeTooltip />}
          cursor={{ fill: "oklch(from var(--color-foreground) l c h / 0.04)" }}
        />
        <Bar dataKey="count" name="Groups" radius={[3, 3, 0, 0]} maxBarSize={56}>
          {data.map((item) => (
            <Cell key={item.status} fill={barColour(item.status)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function GradeTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0];
  if (!point) return null;
  return (
    <div className="border-border bg-card rounded-xl border px-3 py-2.5 text-xs shadow-lg">
      <p className="text-muted-foreground mb-1 font-mono text-[10px] tracking-wider uppercase">
        {label}
      </p>
      <p className="text-foreground font-semibold tabular-nums">
        {point.value} group{point.value === 1 ? "" : "s"}
      </p>
    </div>
  );
}
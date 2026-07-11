"use client";

// Client Component (uses Recharts, which relies on ResizeObserver + hooks).
// D-06: interactive-but-lightweight — hover Tooltip + responsive resize only.
// No zoom/pan/brush for v1. Kept intentionally free of any date/data-fetching
// library to hold the client bundle (and the 1 GB server RAM budget) down.

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

export type MetricPoint = { date: string; value: number | null };

type MetricChartProps = {
  series: MetricPoint[];
  // Optional second series (body composition: body-fat % against weight).
  secondary?: MetricPoint[];
  // Reserved for Claude's discretion (D-06); line is the default.
  chartType?: "line" | "area";
};

// Primary accent = emerald-600 (UI-SPEC reserved accent). Secondary series
// (body composition) = zinc-400. Never introduce a third chart color.
const PRIMARY_STROKE = "#059669";
const SECONDARY_STROKE = "#a1a1aa";
// Chart-internal exception (UI-SPEC): axis ticks 12px / weight 400 / zinc-500.
const AXIS_TICK = { fontSize: 12, fontWeight: 400, fill: "#71717a" } as const;

export default function MetricChart({ series, secondary }: MetricChartProps) {
  // When a secondary series is present, merge on date so both lines share one
  // dataset (Recharts renders multiple <Line>s over a single data array).
  const data = secondary
    ? mergeSeries(series, secondary)
    : series.map((p) => ({ date: p.date, value: p.value }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
        <XAxis
          dataKey="date"
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          minTickGap={24}
        />
        <YAxis
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={40}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          labelStyle={{ fontWeight: 600 }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke={PRIMARY_STROKE}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        {secondary ? (
          <Line
            type="monotone"
            dataKey="secondary"
            stroke={SECONDARY_STROKE}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ) : null}
      </LineChart>
    </ResponsiveContainer>
  );
}

type MergedPoint = { date: string; value: number | null; secondary: number | null };

function mergeSeries(
  primary: MetricPoint[],
  secondary: MetricPoint[],
): MergedPoint[] {
  const byDate = new Map<string, MergedPoint>();
  for (const p of primary) {
    byDate.set(p.date, { date: p.date, value: p.value, secondary: null });
  }
  for (const s of secondary) {
    const existing = byDate.get(s.date);
    if (existing) {
      existing.secondary = s.value;
    } else {
      byDate.set(s.date, { date: s.date, value: null, secondary: s.value });
    }
  }
  return Array.from(byDate.values()).sort((a, b) =>
    a.date < b.date ? -1 : a.date > b.date ? 1 : 0,
  );
}

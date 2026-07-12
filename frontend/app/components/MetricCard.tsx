// Server Component (async; the use-client directive is intentionally absent):
// each card fetches its own metric server-side so a single failing fetch renders
// that card's error state without crashing sibling cards (per-card isolation,
// SC3 graceful degradation).

import {
  getMetricSeries,
  getWorkoutsDaily,
  METRIC_DISPLAY,
  type MetricResult,
} from "@/lib/metrics";
import MetricChart, { type MetricPoint } from "./MetricChart";

type MetricCardProps = {
  name: string;
  range: string;
};

const CARD_CLASS =
  "rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const ERROR_CARD_CLASS =
  "rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950";

// Cards that carry the workouts freshness caveat (CONTEXT §deferred).
const FRESHNESS_CAVEAT_NAMES = new Set(["workouts", "training_load"]);

// Convert a grams-valued metric result to kilograms for display (weight_g → kg).
// Nulls (missing weigh-ins) pass through so the chart's connectNulls still works.
function gramsToKg(
  r: Extract<MetricResult, { ok: true }>,
): MetricResult {
  const toKg = (v: number | null): number | null => (v === null ? null : v / 1000);
  return {
    ...r,
    latest: toKg(r.latest ?? null),
    series: r.series.map((p) => ({ date: p.date, value: toKg(p.value) })),
  };
}

function lastValue(series: MetricPoint[]): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i].value !== null) return series[i].value;
  }
  return null;
}

function formatValue(value: number | null): string {
  if (value === null) return "—";
  // Integer metrics read cleaner without a trailing .0; keep one decimal otherwise.
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export default async function MetricCard({ name, range }: MetricCardProps) {
  const display = METRIC_DISPLAY[name] ?? { title: name, unit: "" };
  const title = display.title;

  // Route the fetch by name so no card ever hits the registry route with an
  // unregistered name (closes the workouts-404 gap).
  let result: MetricResult;
  let secondary: MetricPoint[] | undefined;

  if (name === "workouts") {
    result = await getWorkoutsDaily(range);
  } else if (name === "body_composition") {
    // Body composition = weight (primary) + body-fat % (secondary). Multiple
    // same-day weigh-ins render as-is — one point per event, no dedupe
    // (RESEARCH Open Q2 default / Pitfall 3, a consciously accepted discretion).
    const [weight, bodyFat] = await Promise.all([
      getMetricSeries("weight", range),
      getMetricSeries("body_fat_pct", range),
    ]);
    // The backend `weight` metric is BodyComposition.weight_g — raw grams. The
    // card (and its "kg" unit) render kilograms, so scale the series + latest by
    // 1/1000 here at the display edge; the REST API stays authoritative in grams.
    result = weight.ok ? gramsToKg(weight) : weight;
    if (bodyFat.ok) secondary = bodyFat.series;
  } else {
    result = await getMetricSeries(name, range);
  }

  // (1) Error state — amber card, status/unreachable copy only (no raw detail).
  if (!result.ok) {
    const body =
      result.status === 0
        ? "Couldn't reach the data service. Refresh to try again."
        : `The data service didn't respond (status ${result.status}). Refresh to try again.`;
    return (
      <section className={ERROR_CARD_CLASS}>
        <h2 className="text-xl font-semibold text-amber-800 dark:text-amber-300">
          Couldn't load this chart
        </h2>
        <p className="mt-2 text-base text-amber-800 dark:text-amber-300">{body}</p>
      </section>
    );
  }

  const series = result.series;

  // (2) Empty state — heading + body centered at the chart height, no chart.
  if (series.length === 0) {
    return (
      <section className={CARD_CLASS}>
        <h2 className="text-xl font-semibold">{title}</h2>
        <div
          className="mt-2 flex flex-col items-center justify-center gap-1 text-center"
          style={{ height: 240 }}
        >
          <p className="text-base font-semibold">No {title.toLowerCase()} data yet</p>
          <p className="text-base text-zinc-600 dark:text-zinc-400">
            Sync your Garmin data to see this trend.
          </p>
        </div>
      </section>
    );
  }

  // (3) Populated — title, large Geist-Mono current value + unit, then chart.
  const current = result.latest ?? lastValue(series);

  return (
    <section className={CARD_CLASS}>
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="font-mono text-3xl font-semibold tabular-nums">
          {formatValue(current)}
        </span>
        {display.unit ? (
          <span className="text-sm text-zinc-500">{display.unit}</span>
        ) : null}
      </div>
      <div className="mt-4">
        <MetricChart series={series} secondary={secondary} />
      </div>
      {FRESHNESS_CAVEAT_NAMES.has(name) ? (
        <p className="mt-2 text-sm text-zinc-500">
          Workouts sync on manual backfill — may lag recent activity.
        </p>
      ) : null}
    </section>
  );
}

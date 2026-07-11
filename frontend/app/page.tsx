// Server Component: the single scrollable Longevity Dashboard overview (D-02).
// Reads the ?range= search param (D-03) — Promise-typed in Next 16, so it is
// awaited before use (06-02 SUMMARY) — and renders one MetricCard per D-01
// metric. Each card fetches its own series server-side so a single failing
// fetch is isolated to that card while its siblings still render (SC3).

import RangeSwitcher from "./components/RangeSwitcher";
import MetricCard from "./components/MetricCard";

// D-01 metric order, top → bottom. "body_composition" yields the two-series
// weight + body-fat card; "workouts" is routed off the registry route by
// MetricCard (getWorkoutsDaily → /api/workouts/daily), so it is passed verbatim.
const METRICS = [
  "sleep_score",
  "hrv",
  "resting_hr",
  "vo2max",
  "body_composition",
  "training_load",
  "workouts",
] as const;

// The range whitelist mirrors the backend's fixed set (Plan 06-01); an unknown
// or absent ?range= falls back to the D-03 default rather than reaching the API.
const VALID_RANGES = new Set(["30d", "90d", "1y", "all"]);
const DEFAULT_RANGE = "90d";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const { range: rawRange } = await searchParams;
  const range = rawRange && VALID_RANGES.has(rawRange) ? rawRange : DEFAULT_RANGE;

  return (
    <div className="min-h-screen bg-zinc-50 font-sans text-black dark:bg-black dark:text-zinc-50">
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-16">
        <header className="flex flex-col gap-1">
          <h1 className="text-3xl font-semibold tracking-tight">Longevity Dashboard</h1>
          <p className="text-zinc-600 dark:text-zinc-400">
            Your key health trends at a glance.
          </p>
        </header>

        <RangeSwitcher />

        {METRICS.map((name) => (
          <MetricCard key={name} name={name} range={range} />
        ))}
      </main>
    </div>
  );
}

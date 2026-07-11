// Server-only metric fetch helpers. This module runs exclusively in Server
// Components over the internal Docker network (BACKEND_URL=http://backend:8000).
// It deliberately does NOT introduce a NEXT_PUBLIC_ variable or any browser-side
// fetch — the backend is never reachable from the client (threat T-06-05), and no
// raw backend detail is surfaced (T-06-06; callers show only status + fixed copy).
//
// Extracted from app/page.tsx's getActivities: same discriminated FetchResult
// shape, same load-bearing status-0 "Backend unreachable" catch branch so a
// backend outage degrades gracefully per-card (SC3) instead of throwing.

import type { MetricPoint } from "@/app/components/MetricChart";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

export type MetricResult =
  | {
      ok: true;
      series: MetricPoint[];
      direction?: string;
      latest?: number | null;
    }
  | { ok: false; status: number; detail: string };

// Shape returned by GET /api/metrics/{name}.
type MetricsResponse = {
  direction?: string;
  latest?: number | null;
  series?: MetricPoint[];
};

// Shape returned by GET /api/workouts/daily (value = daily workout count).
type WorkoutsResponse = {
  series?: { date: string; value: number | null }[];
};

/**
 * Fetch a registry-backed metric time series for a range.
 * Never throws — returns the discriminated { ok:false } variant on any failure,
 * with status:0 when the backend is unreachable.
 *
 * NOTE: `workouts` is NOT a registry metric — use getWorkoutsDaily for it.
 * Calling getMetricSeries("workouts", ...) would 404 on the registry route.
 */
export async function getMetricSeries(
  name: string,
  range: string,
): Promise<MetricResult> {
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/metrics/${name}?range=${range}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, status: res.status, detail: body.detail ?? res.statusText };
    }
    const data = (await res.json()) as MetricsResponse;
    return {
      ok: true,
      series: data.series ?? [],
      direction: data.direction,
      latest: data.latest ?? null,
    };
  } catch (err) {
    return { ok: false, status: 0, detail: `Backend unreachable: ${String(err)}` };
  }
}

/**
 * Fetch the daily workouts rollup, mapped into the SAME discriminated shape as
 * getMetricSeries so a MetricCard can render it through the identical
 * error/empty/populated path. `value` is the daily workout count.
 */
export async function getWorkoutsDaily(range: string): Promise<MetricResult> {
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/workouts/daily?range=${range}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, status: res.status, detail: body.detail ?? res.statusText };
    }
    const data = (await res.json()) as WorkoutsResponse;
    const series: MetricPoint[] = (data.series ?? []).map((p) => ({
      date: p.date,
      value: p.value,
    }));
    const latest = series.length > 0 ? series[series.length - 1].value : null;
    return { ok: true, series, latest };
  } catch (err) {
    return { ok: false, status: 0, detail: `Backend unreachable: ${String(err)}` };
  }
}

// Display config only (canonical UI-SPEC titles + units). This is NOT a second
// source of truth for the metric→DB-column mapping — the backend METRICS
// registry stays authoritative (RESEARCH "Don't hand-roll"); these are labels.
export type MetricDisplay = { title: string; unit: string };

export const METRIC_DISPLAY: Record<string, MetricDisplay> = {
  resting_hr: { title: "Resting heart rate", unit: "bpm" },
  hrv: { title: "HRV", unit: "ms" },
  sleep_score: { title: "Sleep score", unit: "/100" },
  vo2max: { title: "VO₂max", unit: "ml/kg/min" },
  weight: { title: "Body composition", unit: "kg" },
  body_fat_pct: { title: "Body fat", unit: "%" },
  body_composition: { title: "Body composition", unit: "kg" },
  training_load: { title: "Training load", unit: "" },
  workouts: { title: "Workouts", unit: "/day" },
};

// Server Component: fetches the user's Garmin activities from the backend at
// request time (fetch is uncached by default in the App Router).

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

type Activity = {
  activityId: number;
  activityName?: string;
  activityType?: { typeKey?: string };
  startTimeLocal?: string;
  distance?: number; // meters
  duration?: number; // seconds
  calories?: number;
};

type FetchResult =
  | { ok: true; activities: Activity[] }
  | { ok: false; status: number; detail: string };

async function getActivities(): Promise<FetchResult> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/activities?limit=15`, {
      cache: "no-store",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, status: res.status, detail: body.detail ?? res.statusText };
    }
    return { ok: true, activities: await res.json() };
  } catch (err) {
    return { ok: false, status: 0, detail: `Backend unreachable: ${String(err)}` };
  }
}

function formatDistance(meters?: number): string {
  if (!meters) return "—";
  return `${(meters / 1000).toFixed(2)} km`;
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.round(seconds % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

export default async function Home() {
  const result = await getActivities();

  return (
    <div className="min-h-screen bg-zinc-50 font-sans text-black dark:bg-black dark:text-zinc-50">
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-16">
        <header className="flex flex-col gap-1">
          <h1 className="text-3xl font-semibold tracking-tight">Garmin Fetcher</h1>
          <p className="text-zinc-600 dark:text-zinc-400">Your recent activities.</p>
        </header>

        {!result.ok ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-800 dark:bg-amber-950">
            <p className="font-medium">Could not load activities (status {result.status}).</p>
            <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-600 dark:text-zinc-400">
              {result.detail}
            </pre>
          </div>
        ) : result.activities.length === 0 ? (
          <p className="text-zinc-500">No activities found.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {result.activities.map((a) => (
              <li
                key={a.activityId}
                className="flex flex-col gap-1 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium">{a.activityName ?? "Untitled"}</span>
                  <span className="text-xs uppercase tracking-wide text-zinc-500">
                    {a.activityType?.typeKey ?? "activity"}
                  </span>
                </div>
                <div className="flex flex-wrap gap-4 text-sm text-zinc-600 dark:text-zinc-400">
                  <span>{a.startTimeLocal ?? "—"}</span>
                  <span>{formatDistance(a.distance)}</span>
                  <span>{formatDuration(a.duration)}</span>
                  {a.calories ? <span>{Math.round(a.calories)} kcal</span> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

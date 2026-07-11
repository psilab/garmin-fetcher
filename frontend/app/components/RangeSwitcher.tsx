"use client";

// First interactive control in the app — the global range switcher (D-03).
// URL-driven per RESEARCH Pattern 1: clicking a range pushes ?range= and the
// Server Component (page.tsx) refetches every chart for that window. No chart
// data is ever held in client state here — the URL is the single source of
// truth. useRouter + useSearchParams from next/navigation are the confirmed
// Next 16 App Router navigation idiom (06-02 SUMMARY + in-container
// node_modules/next/dist/docs use-router.md — router.push() re-runs the Server
// Component, unlike window.history.pushState which would not refetch).

import { useRouter, useSearchParams } from "next/navigation";

const RANGES = [
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "1y", label: "1 year" },
  { value: "all", label: "All time" },
] as const;

// Default selection when no ?range= is present (D-03).
const DEFAULT_RANGE = "90d";

const BASE_BUTTON = "rounded-md px-3 py-1.5 text-sm transition-colors";
// Active = accent emerald (UI-SPEC Color reserved item 2); inactive = neutral zinc.
const ACTIVE_BUTTON = "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-black";
const INACTIVE_BUTTON =
  "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800";

export default function RangeSwitcher() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Read the active range straight from the URL so the highlighted button always
  // matches what the Server Component rendered.
  const current = searchParams.get("range") ?? DEFAULT_RANGE;

  function selectRange(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("range", value);
    // Relative "?..." keeps the current pathname; scroll:false avoids a jump
    // since the switcher is pinned at the top of the column.
    router.push(`?${params.toString()}`, { scroll: false });
  }

  return (
    <div role="group" aria-label="Select time range" className="flex flex-wrap gap-2">
      {RANGES.map((r) => {
        const active = r.value === current;
        return (
          <button
            key={r.value}
            type="button"
            aria-pressed={active}
            onClick={() => selectRange(r.value)}
            className={`${BASE_BUTTON} ${active ? ACTIVE_BUTTON : INACTIVE_BUTTON}`}
          >
            {r.label}
          </button>
        );
      })}
    </div>
  );
}

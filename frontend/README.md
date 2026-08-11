# Dashboard

React 19 + TypeScript + Vite. Reads the FastAPI backend for live data and
`src/data/metricsSnapshot.ts` for benchmark figures.

## Run it

Three processes, in three terminals, from the repository root unless noted.

```powershell
# 1. backend API
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload

# 2. dashboard (from frontend/)
npm run dev            # http://localhost:5173

# 3. optional — only needed for the Runs page write path
docker compose up -d redis
.\.venv\Scripts\python.exe scripts\run_eval_worker.py
```

The dashboard works with only step 1. Without it, every live panel shows an
"API offline" state rather than an empty table — that distinction is
deliberate.

## How data reaches the screen

Two sources, kept visibly separate:

| Source | Powers | Freshness |
|---|---|---|
| FastAPI over the Vite `/api` proxy | Runs, Review queue, the health pill | live |
| `src/data/metricsSnapshot.ts` | Overview, Retrieval, Judges | edited by hand as you measure |

The proxy is configured in `vite.config.ts`; it rewrites `/api/x` to `/x` and
targets `http://127.0.0.1:8000`. This is why the browser never makes a
cross-origin request and the backend needs no CORS middleware. For a real
deployment, set `VITE_API_BASE_URL` at build time instead.

## Adding a measurement

Every number on screen is tagged `measured`, `placeholder` or `not_measured`.
To promote one:

1. Run the code and record the actual output.
2. Open `src/data/metricsSnapshot.ts` and swap `notMeasured(...)` for
   `measured(value, source, date, command)`.
3. Reload. The claim-readiness checklist on the Overview page recomputes
   itself — nothing there is ticked by hand.

A `NotMeasuredMetric` has no `value` field, so TypeScript will not let you
render a number for something that was never measured. If you find yourself
wanting to write `measured(0, ...)` to fill a gap, that is the type system
catching a claim you cannot support.

## Checks

```powershell
npm run build     # tsc -b && vite build — the typecheck is the real gate
npm run lint      # oxlint
```

# Frontend: operator dashboard

Vite + React + TypeScript + Leaflet. It connects to the backend over server-sent events
(`/stream`), so the map, trips table, alerts and headline numbers update live.

## Run locally

```bash
cd frontend
npm install
npm run dev                                          # uses the Railway backend by default
VITE_API_URL=http://localhost:8000 npm run dev       # or point it at a local backend
```

## Deploy on Vercel

1. Vercel -> Add New -> Project -> import the `ada-hackathon` GitHub repo.
2. **Root Directory** = `frontend`. Vercel detects Vite (build `npm run build`, output `dist`).
3. Optional: Environment Variables -> `VITE_API_URL` = the backend URL (defaults to the Railway production URL).
4. Deploy. Every push to `main` redeploys automatically.

## Pages and routing

React Router (`react-router`, declarative mode). `App.tsx` is the layout: it opens **one** live
connection (`useWorldState`) and passes the snapshot to each page.

To add a page:
1. Create `src/pages/MyPage.tsx` exporting `function MyPage({ state }: { state: WorldSnapshot })`.
2. Add `<Route path="/my-page" element={<MyPage state={state} />} />` in `App.tsx`.
3. Add a `<NavLink to="/my-page">My page</NavLink>` in the header `nav`.

`vercel.json` rewrites every path to `index.html`, so reloading `/fleet` on Vercel doesn't 404.

## Files

| File | What it does |
|---|---|
| `src/api.ts` | Types mirroring the backend, the SSE hook, and POST helpers |
| `src/MapView.tsx` | Leaflet map: places, vehicles, current routes, incidents; click-to-place mode |
| `src/App.tsx` | Layout + routes; Dashboard: headline numbers, event controls, alerts, event log, trips table |
| `src/AgentPanel.tsx` | AI dispatcher: live agent trace, option cards, approve/reject, notification drafts |
| `src/pages/FleetPage.tsx` | Example subpage: each vehicle's projected schedule |
| `src/format.ts` | Shared formatting helpers |
| `src/styles.css` | Dark operations-centre theme |

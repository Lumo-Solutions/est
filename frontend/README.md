# InstallTec Estimating -- frontend

React 18 + TypeScript + Vite + Tailwind CSS + AG Grid Community. See
`docs/module-frontend-phase8-plan.md` for the stack decisions and
sub-phase breakdown, and `docs/preconstruction-build-brief.md`'s Phase 8
for the full screen list.

## Development

```
npm install
npm run dev       # http://localhost:5173, proxies /api to the backend
                   # (VITE_BACKEND_ORIGIN, default http://localhost:8001)
npm run build      # type-check + production build
npm run test       # vitest (unit/component)
npm run e2e        # Playwright smoke tests, using the machine's installed
                   # Chrome -- never runs `playwright install`
npm run lint       # oxlint
```

Auth is a backend-for-frontend flow (HTTP-only session cookie + a
double-submit CSRF cookie); the backend must be reachable at `/api/v1`
for anything past the login screen to work. In dev that's the Vite proxy
above; in the built image it's nginx (see `Dockerfile` / `nginx.conf`)
proxying to the `backend` container on the same origin, so cookies never
cross origins and no CORS configuration is needed anywhere.

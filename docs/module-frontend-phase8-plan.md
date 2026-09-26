# Phase 8 plan: frontend

Per `docs/preconstruction-build-brief.md`'s Phase 8. Split into sub-phases
per the brief's own "split into sub-phases if large" allowance -- this is
easily the largest single phase in the build. Every default below is this
plan's own choice where the brief leaves it open.

## 0. What already exists on the backend (confirmed by reading the code)

The brief's "Auth" bullet describes something that **is already fully
built** server-side -- this phase wires the frontend to it, it does not
build it:

- `app/api/v1/routes/auth.py`: `GET /api/v1/auth/login` (builds the
  Keycloak authorize URL with PKCE, stores state/verifier/nonce
  server-side), `GET /api/v1/auth/callback` (exchanges the code, creates
  an encrypted server-side session, sets the session + CSRF cookies,
  audits the login), `POST /api/v1/auth/logout` (RP-initiated Keycloak
  logout + clears cookies), `GET /api/v1/auth/me` (sub/tenant_id/roles/acr
  for the current session), `GET /api/v1/auth/step-up` (re-authorizes
  with `acr_values` for MFA step-up, per `security/deps.py::
  require_mfa_step_up`).
- `app/security/csrf.py::CsrfMiddleware`: double-submit cookie check on
  every non-safe method for cookie-authenticated requests (bearer-token
  requests are exempt) -- the frontend must echo the CSRF cookie's value
  back in the `settings.csrf_header` header (confirmed name at
  implementation time from `deploy/.env`/`Settings.csrf_header`) on every
  mutating fetch.
- `app/core/errors.py::StepUpRequiredError`: `error_type =
  "urn:installtec:step-up-required"` in the JSON problem-details body --
  the frontend's fetch wrapper detects this exact string to redirect to
  `/api/v1/auth/step-up?next=<current-url>` rather than showing a generic
  error.
- Every route already enforces authorization server-side (RLS + role
  checks) -- the frontend hiding an action the role can't perform is
  purely a UX nicety, never the real gate, exactly as the brief says.

No CORS configuration exists on the backend, and none is added: the
frontend's nginx reverse-proxies `/api/*` to the `backend` container on
the **same origin** the browser loads the SPA from, so the session/CSRF
cookies are always same-origin and CORS is never needed -- the simplest,
most secure option for cookie-based auth, and the default this plan picks
where the brief leaves the serving topology open.

## 1. Tech stack (concrete choices, no further "what version of X" gaps)

- React 18, TypeScript, Vite, Tailwind CSS, **AG Grid Community** (never
  Enterprise -- standing license constraint). React Router for routing.
  TanStack Query for server-state (fetch caching/invalidation) -- no
  Redux; nothing in this app needs cross-screen client-only state beyond
  what a query cache + URL params already cover.
- No CDN, no web fonts fetched from the internet, no telemetry (standing
  constraint) -- Tailwind's default system-font stack is used as-is
  (`font-sans` -> system UI fonts), never a `@font-face` pointing
  externally; every JS dependency is bundled by Vite into the built
  assets, nothing loaded from a `<script src="https://...">` tag.
- pdf.js (bundled, not CDN-loaded) for the PDF half of the split pane.
  DXF sheets: the brief says "server-rendered SVG" -- Phase 8 does not
  change the backend to add an SVG-rendering endpoint (out of scope for a
  frontend phase); a minimal one is added only if no equivalent already
  exists (checked at 8b implementation time: `app/takeoff/dxf.py`'s
  existing extraction gives geometry, not a renderable SVG document, so a
  small new endpoint is expected).
- Served by nginx (multi-stage Dockerfile: `node:*-alpine` build stage,
  `nginx:alpine` runtime stage), matching `deploy/docker-compose.yml`'s
  existing `frontend` service stub (`build: ../frontend`, port 3000:80).
  `profiles: ["frontend"]` is removed once the scaffold builds and serves
  a real page (end of 8a), per the brief's explicit instruction.

## 2. Sub-phases

- **8a -- Foundation**: Vite/React/TS/Tailwind scaffold; the typed API
  client (fetch wrapper: same-origin `/api/v1` base, CSRF header
  injection, step-up-required interception + retry-after-reauth,
  problem-details error parsing); the auth flow (login redirect, callback
  landing route, `/auth/me`-backed session context, logout); app shell
  (nav, role-aware action visibility helper); routing skeleton for every
  screen below (placeholder pages, wired up as each later sub-phase
  lands); nginx config + Dockerfile; removes the compose profile gate;
  vitest + Playwright wiring (config only -- the first real specs land
  with 8b's first real screen).
- **8b -- Projects, drawings, takeoff split-pane**: projects list/detail;
  drawing upload + sheet index; the split-pane viewer (pdf.js /
  server-rendered SVG, measurements overlaid with confidence indicators,
  non-destructive overrides, two-point calibration UI).
- **8c -- Typology + BOQ**: typology cluster review; BOQ import wizard
  (mapping, dry run, commit); reconciliation grid (AG Grid, virtualised,
  a generated-5,000-line-BOQ performance test); link-suggestion
  accept/reject; unlinked-measurements view.
- **8d -- Procurement + bid leveling**: packages/RFQs (draft, dispatch,
  resend); quarantine/review queues; quote review/acceptance; version
  promotion; bid-leveling matrix with exclusion flags + citations.
- **8e -- Settlement + export + win/loss**: settlement cockpit (live
  simulation sliders, saved scenarios, submit/approve/reject, SoD shown
  in the UI); export screen (generated or original, with the fidelity
  report); win/loss capture.
- **8f -- Admin + audit + closeout**: admin screens (taxonomy, approval
  policies, tolerances, layer/style-to-trade mapping, reason codes,
  vendor regions); read-only audit viewer; a final pass filling any
  vitest/Playwright gaps left by earlier sub-phases; `docs/build-log.md`
  consolidated for the whole phase.

Each sub-phase gets its own branch (`feat/8a-frontend-foundation`, etc.),
its own commits, merged `--no-ff` once its own vitest suite (and
Playwright smoke test, once one exists) is green -- same ritual as every
backend phase this build has used, adapted to `npm test`/`npx playwright
test` in place of `make test-unit`/`make test-integration`. Every UI
change is verified live in a browser (via the Chrome devtools MCP tools
already available in this environment) before a sub-phase is called
done, not just by its automated tests -- per this session's own standing
"start the dev server and use the feature in a browser" instruction.

## 3. Testing

- **vitest**: component/logic unit tests (the API client's CSRF/step-up
  interception logic, the role-visibility helper, form validation,
  grid-column formatting helpers) -- co-located with the code they test
  (`*.test.tsx` alongside the component), matching the backend's own
  "tests alongside code" convention.
- **Playwright**: "using the pre-installed browser... don't download
  browsers" -- `playwright.config.ts` sets `use: { channel: 'chrome' }`
  (or an explicit `executablePath`, resolved at 8a implementation time
  against whatever Chrome/Chromium this environment actually has) and
  the install step is `npx playwright install --with-deps` **never run**
  in this build (no browser download) -- CI/local environments that
  already have Chrome present are the only supported target. One smoke
  spec per module's own "one happy path" (per the brief), plus a login
  smoke test in 8a.
- **AG Grid performance**: 8c's reconciliation-grid test generates 5,000
  synthetic BOQ rows client-side (a test fixture, not a real import) and
  asserts the grid remains responsive (row virtualization means only the
  visible rows ever mount -- the test asserts the DOM node count stays
  bounded regardless of the 5,000-row dataset, not a subjective "feels
  smooth" measure).

## 4. Explicitly out of scope for this phase

- Any new backend endpoint beyond the one narrow exception noted in §1
  (DXF-to-SVG rendering, if nothing equivalent exists) -- this is a
  frontend phase against an already-complete API.
- Offline/PWA support, i18n/l10n, dark mode -- none requested by the
  brief or SRS.
- Visual design polish beyond "a competent, usable Tailwind-styled admin
  tool" -- this is a working platform for an internal estimating team,
  not a marketing site.

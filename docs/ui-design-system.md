# InstallTec Estimating — UI design system

Phase 4 of `docs/ui-qa-brief.md`. Written first, per the brief, before any
page is restyled. Generated with the `ui-ux-pro-max` skill (`--design-system`
search: "construction estimating procurement B2B enterprise SaaS dense data
dashboard professional", supplemented with targeted `typography`/`color`/`ux`
domain searches) and adapted to this app's real constraints: air-gapped (no
CDN fonts/icons), Tailwind v4 (CSS-first `@theme`, no `tailwind.config.js`),
AG Grid Community (Theming API, not the legacy CSS-file themes), and — most
importantly — a large amount of already-correct, already-tested functional
UI from Phases 0–3 that this phase re-skins, not rebuilds.

## 1. Product style

**Professional enterprise B2B for construction estimating and procurement.**
Dense but calm, data-first, built for long working sessions (an estimator or
procurement head lives in this tool for hours, not minutes). Concretely:

- Information density over whitespace-for-its-own-sake — this is a working
  tool, not a marketing site. But density must never come at the cost of
  legibility: generous *vertical rhythm* inside a table row, tight *horizontal*
  padding.
- Calm, not flashy. No gradients, no drop-shadows beyond a 1-level elevation
  for popovers/modals, no decorative illustration. Every color used is either
  structural (neutral) or means something (brand action, or a status).
  Matches the skill's own "Data-Dense Dashboard" style anti-patterns:
  *ornate design*, *no filtering* — both avoided here.
  Anti-pattern this rules out concretely: `EnterpriseGateway`'s own
  suggested pattern (hero/video, logo carousel, mega-menu) is the *landing
  page* recipe the skill returned for the "enterprise SaaS" query — explicitly
  **not applicable** here. This app has no logged-out marketing surface at
  all; every screen is post-login, internal, task-focused. Ignored on purpose.
- Numbers are the product. Every page that shows AED amounts, percentages,
  or quantities gets tabular figures (see Typography) and consistent
  formatting (see `frontend/src/lib/format.ts`'s `formatMoney`/
  `formatMarginPct`, both already built in Phase 2/3 — Phase 4 is the pass
  that makes every remaining ad-hoc `.toFixed()` call use them).

## 2. Tokens

### 2.1 Color

Neutral base: Tailwind's `slate` scale — already the de facto choice across
every page built in Phases 0–3 (confirmed by grep: `slate-` appears in every
page component). Formalizing it, not replacing it, is the lowest-risk path
that keeps hundreds of already-QA'd, already-tested elements visually
consistent with the handful this phase explicitly restyles.

One brand accent: a corporate blue, distinct enough from `slate` to read as
"the app's color" without competing with semantic colors. Chosen over the
skill's own generic SaaS-blue suggestions (`#2563EB`, `#1E40AF`, `#6366F1`)
for one reason: it must pass 4.5:1 contrast on **both** white (`#FFFFFF`) and
the app's own off-white surface color, as a link/text/icon color, not just as
a button fill — `#1D4ED8` (Tailwind `blue-700`) does; `#3B82F6` (`blue-500`,
a common default) does not (2.9:1 on white, fails AA for text).

| Token | Hex | Tailwind ref | Use | Contrast on white |
|---|---|---|---|---|
| `--color-neutral-50` … `-950` | slate scale | `slate-50`…`slate-950` | backgrounds, borders, body text | — |
| `--color-brand` | `#1D4ED8` | `blue-700` | primary buttons, links, focus rings, active nav | 6.3:1 (AA/AAA text) |
| `--color-brand-hover` | `#1E40AF` | `blue-800` | brand hover/active state | 8.6:1 |
| `--color-brand-subtle` | `#EFF6FF` | `blue-50` | selected-row / active-tab background | — |
| `--color-success` | `#059669` | `emerald-600` | approved, accepted, verified, matched | 4.5:1 |
| `--color-warning` | `#D97706` | `amber-600` | pending, expiring soon, draft-needs-attention | 4.6:1 |
| `--color-danger` | `#DC2626` | `red-600` | rejected, expired, error, destructive action | 5.9:1 |
| `--color-info` | `#0284C7` | `sky-600` | informational badges, neutral in-progress states | 4.6:1 |

All four semantic colors are used as **text-on-tint** (e.g. `text-emerald-700`
on `bg-emerald-100`) for badges — that pairing is 5.7:1+ for all four, comfortably
AA, and is what most pages already do today (Phase 2 built several `STATUS_STYLES`
maps in exactly this shape) — Phase 4 consolidates them into one shared
`Badge` component/token set instead of nine near-identical per-page copies.

Never introduce a one-off hex value on any page. If a new state needs a
color, it maps to one of the four semantic tokens above, or it's neutral.

### 2.2 Typography

**IBM Plex Sans**, self-hosted via `@fontsource/ibm-plex-sans` (npm, MIT
licensed, no CDN — satisfies the brief's air-gapped constraint directly).
Chosen over the skill's flashier "Dashboard Data" pairing (Fira Code
headings) because a monospace *heading* font reads as a dev-tool aesthetic,
not an estimating tool a director presents numbers from; IBM Plex Sans's
own design brief (IBM's enterprise/financial product family) is a closer
match to "professional enterprise B2B... data-first" than a generic
Inter/system-ui default, and it has first-class tabular-figure support.

- One family, weights 400/500/600/700 — no separate heading font. Matches
  the skill's own "Minimal Swiss" (Inter) reasoning (*"single font family
  with weight variations, ultimate simplicity"*) applied to IBM Plex Sans
  instead.
- **Tabular figures for numbers** (the brief's explicit requirement):
  `font-variant-numeric: tabular-nums` on every AED amount, percentage,
  quantity, and table cell containing a number — IBM Plex Sans supports the
  OpenType `tnum` feature natively. A `.tabular-nums` utility class (Tailwind
  v4 ships this as `tabular-nums` already) applied wherever `formatMoney`/
  `formatMarginPct`/a raw quantity renders.
- Install: `npm install @fontsource/ibm-plex-sans` (weights 400/500/600/700),
  imported once in `main.tsx` or `index.css` (`@import
  '@fontsource/ibm-plex-sans/400.css';` etc.) — bundled by Vite, never a
  `<link>` to fonts.googleapis.com.

| Token | Value | Use |
|---|---|---|
| `--font-sans` | `'IBM Plex Sans', system-ui, sans-serif` | everything |
| `text-xs` | 12px / 16px line-height | table meta, badges |
| `text-sm` | 14px / 20px | default body, form inputs, table cells |
| `text-base` | 16px / 24px | page body copy where used |
| `text-lg` | 18px / 28px | section headings |
| `text-xl` | 20px / 28px | page titles (`<h1>`) |

Line-height 1.4–1.5 for body/table text (denser than the skill's generic
1.5–1.75 body-copy guidance — deliberate, for a data-dense tool where
excess line-height wastes vertical space in every table row; 1.5+ is kept
for actual prose, e.g. help text and empty-state copy).

### 2.3 Spacing

Tailwind's default scale, used as-is (no custom spacing tokens) — a 4px
base unit (`space-1` = 4px) is already what every existing page uses.
Formalized defaults:

- Page padding: `p-6` (24px) — matches every page today.
- Card/section padding: `p-4` (16px).
- Table cell padding: `px-3 py-2` (12px/8px) — denser than the page default,
  intentional for the "data-dense" style.
- Gap between form fields: `gap-2` to `gap-3` (8–12px).

### 2.4 Radius

- `rounded` (4px, Tailwind default) for buttons, inputs, badges, table
  containers — matches almost every existing page already.
- `rounded-lg` (8px) for modals/drawers/cards that sit visually "above" the
  page (matches `Modal.tsx`, built in Phase 3, already using `rounded-lg`).
- Never fully rounded (`rounded-full`) except genuine circular elements
  (avatar-style initials, if ever added) — not buttons or badges.

### 2.5 Elevation

Flat by default. Two levels only:

- **Level 0** (default): `border border-slate-200`, no shadow — every card,
  table, section on a normal page.
- **Level 1** (overlay): `shadow-lg` — modals, drawers, dropdown menus.
  Matches `Modal.tsx`'s existing `shadow-lg`.

No level 2+. A flat, bordered surface reads as "part of the page you're
working in"; a shadow reads as "temporarily on top of it" — exactly the
modal/non-modal distinction this app needs, nothing more.

## 3. Tailwind v4 tokens (drop into `frontend/src/index.css`)

```css
@import "tailwindcss";
@import "@fontsource/ibm-plex-sans/400.css";
@import "@fontsource/ibm-plex-sans/500.css";
@import "@fontsource/ibm-plex-sans/600.css";
@import "@fontsource/ibm-plex-sans/700.css";

@theme {
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;

  --color-brand: #1D4ED8;       /* blue-700 */
  --color-brand-hover: #1E40AF; /* blue-800 */
  --color-brand-subtle: #EFF6FF;/* blue-50 */

  --color-success: #059669;  /* emerald-600 */
  --color-success-subtle: #D1FAE5; /* emerald-100 */
  --color-warning: #D97706;  /* amber-600 */
  --color-warning-subtle: #FEF3C7; /* amber-100 */
  --color-danger: #DC2626;   /* red-600 */
  --color-danger-subtle: #FEE2E2;  /* red-100 */
  --color-info: #0284C7;     /* sky-600 */
  --color-info-subtle: #E0F2FE;    /* sky-100 */
}
```

This makes `bg-brand`, `text-brand`, `border-brand`, `bg-success-subtle`
`text-success`, etc. available as first-class Tailwind utilities everywhere,
replacing one-off `bg-blue-700`/`bg-emerald-600` literals so a future palette
change is a one-file edit.

## 4. Components

### 4.1 App shell (`AppShell.tsx`)
- Sidebar: fixed-width (240px at ≥1280px, collapsible to icon-only at
  1024px — see Layout targets below), `bg-white border-r border-slate-200`.
  Project context (when inside a project) shown as a small header block
  above the project nav items: project code + name, `text-sm font-medium`.
- Top bar: `h-14 border-b border-slate-200 bg-white`, breadcrumb-style
  location on the left (new — see 4.9), user/role menu on the right
  (already exists, gets `--color-brand` focus ring).
- Active nav item: `bg-brand-subtle text-brand font-medium border-l-2
  border-brand` (replacing today's plain `NavLink` active-class default).

### 4.2 Buttons
Three variants, all `rounded text-sm font-medium px-3 py-1.5`, all get
`disabled:opacity-50 disabled:cursor-not-allowed` and a `transition-colors
duration-150`:
- **Primary**: `bg-brand text-white hover:bg-brand-hover`. One per view —
  the single most important action (Submit, Save, Create).
- **Secondary**: `border border-slate-300 text-slate-700 hover:bg-slate-50`.
  Cancel, Retry, secondary actions.
- **Destructive**: `border border-red-300 text-red-700 hover:bg-red-50`
  (text-only "Reject"/"Delete" actions already mostly use this shape;
  formalizing it). A genuinely destructive *primary* action (rare in this
  app — e.g. none found that isn't already behind a confirm step) would be
  `bg-danger text-white hover:bg-red-700`.

Every button that triggers a mutation shows a pending state (already
implemented everywhere via `disabled={mutation.isPending}` — Phase 4 keeps
this, doesn't change the mechanism) and — new — a small inline spinner
(shared `Spinner.tsx`, see 4.7) when pending, not just a disabled/greyed
button with no motion (the skill's own "Loading Indicators" guidance:
show a spinner/skeleton for anything that can exceed 300ms, several of
this app's mutations legitimately do).

### 4.3 Forms
- Text input / textarea / select: `rounded border border-slate-300 px-2
  py-1.5 text-sm focus:border-brand focus:ring-1 focus:ring-brand
  focus:outline-none`. Every input gets an associated `<label>` (accessibility
  requirement — several current inputs use only a `placeholder`, which
  Phase 4's accessibility pass replaces with a real, visually-present or
  `sr-only` label per input).
- Field error: `text-xs text-danger mt-1`, directly under the field (not a
  page-level toast) — already the pattern for every mutation's `isError`
  display built across Phases 0–3; Phase 4 makes it visually consistent
  (same red, same size) rather than changing the mechanism.
- Required-field marker: none needed today (no form mixes required and
  optional fields ambiguously enough to need one), revisit if Phase 4's
  page-by-page pass finds one that does.

### 4.4 Tables & the AG Grid theme
Two table mechanisms exist and both stay:
1. **Plain HTML tables** (`<table>`) for most list views — get a shared
   `Table`/`Th`/`Td` styling convention: `text-left text-sm`, header row
   `border-b border-slate-200 text-slate-500 font-medium`, body rows
   `border-b border-slate-100 hover:bg-slate-50` (row hover — the skill's own
   guidance: *"change cursor and add subtle visual change"* on interactive
   rows), numeric columns `text-right tabular-nums`.
2. **AG Grid Community** (`BoqReconciliationGrid.tsx`, the 5,000-row-tested
   grid, and any bid-leveling-matrix-style grid) keeps `themeQuartz` (AG
   Grid's Theming API, not a CSS file) but themed to match:

```ts
const installtecGridTheme = themeQuartz.withParams({
  accentColor: '#1D4ED8',
  headerBackgroundColor: '#F8FAFC', // slate-50
  headerTextColor: '#475569',       // slate-600
  oddRowBackgroundColor: '#FFFFFF',
  rowHoverColor: '#F8FAFC',
  fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
  fontSize: 13,
})
```

Performance is a hard constraint here, not a style nicety: the 5,000-row
test (Phase 0/2's own benchmark) must stay green. Theming API params are a
CSS-variable-level change AG Grid already optimizes for — this does not
touch row virtualization, column virtualization, or any AG Grid perf
setting, so no regression is expected, but the 5,000-row spec is re-run as
part of this page's own QA before being considered done, not assumed safe.

### 4.5 Tabs
Already used (`AdminPage.tsx`'s six tabs). Formalize as: `border-b
border-slate-200` container, each tab `px-3 py-2 text-sm font-medium`,
active tab `text-brand border-b-2 border-brand -mb-px`, inactive `text-slate-500
hover:text-slate-700`.

### 4.6 Modals & drawers
`Modal.tsx`/`TextPromptModal.tsx`/`ConfirmModal.tsx` (built in Phase 3) are
the shared mechanism — Phase 4 does not replace them, only re-skins to
tokens (backdrop `bg-slate-900/40` stays, dialog `rounded-lg shadow-lg`
stays, add `--color-brand` to the primary/submit button inside them).
A **drawer** variant (slide-in from the right, for a future "detail
without leaving the list" pattern) is not needed by any page today —
not built speculatively.

### 4.7 Toasts / inline feedback
No global toast system exists today, and every mutation's success/error
feedback is already inline (next to the control that triggered it) —
correct per the skill's own "Submit Feedback"/"Loading Indicators"
guidance (*"show loading then success/error state... near the problem"*)
and consistent with this app's dense, no-modal-interruption feel. Phase 4
does **not** introduce a global toast component — that would be a new
interaction pattern competing with the existing inline one, not a
restyle. New in this phase: a tiny shared `Spinner.tsx` (a single
`animate-spin` SVG, `--color-brand` stroke) for the loading-button state
in 4.2.

### 4.8 Badges (every status)
One shared `Badge` component, `rounded px-2 py-0.5 text-xs font-medium`,
color from the semantic token set:

| Status family | Example values | Token |
|---|---|---|
| Draft / pending / not started | `draft`, `pending_verification`, `queued` | `warning` |
| Active / approved / accepted / verified / matched | `approved`, `accepted`, `verified`, `matched`, `active` | `success` |
| Rejected / expired / error / mismatch | `rejected`, `expired`, `arithmetic_mismatch` | `danger` |
| In progress / informational | `extracting`, `indexing`, `submitted` | `info` |
| Inactive / archived / dismissed | `inactive`, `dismissed`, `cancelled` | neutral (`bg-slate-100 text-slate-600`) |

Replaces the ~6 near-duplicate `STATUS_STYLES` maps built independently
across Phases 0–3 (`ProjectDetailPage.tsx`, `TypologyPage.tsx`, and others
found during the page-by-page pass) with one component + one status→token
mapping table per page (the mapping differs — a `TypologyClusterStatus` and
a `DrawingStatus` don't share a vocabulary — but the *component* and the
four tokens it draws from are shared).

### 4.9 Empty states
Every list already has some empty-state text (Phase 2's QA pass added the
ones that were missing entirely). Phase 4 formalizes the *shape*: a short
sentence (`text-sm text-slate-500`) plus, where a create action exists and
the viewer's role can use it, a call-to-action button directly below it —
not just prose. Applied page-by-page as each page's specific empty state
is reviewed, not a generic empty-state component (the CTA differs too much
page to page — "Create a project", "Upload a drawing", "Detect clusters" —
to abstract usefully beyond the text+optional-button shape.)

### 4.10 Skeleton loaders
Today every page shows a plain "Loading..." text line. Phase 4 replaces
this with a shared `Skeleton.tsx` (a `bg-slate-200 animate-pulse rounded`
block sized to roughly match the content about to appear — a few
table-row-shaped bars for a list, a card-shaped block for a detail view)
on the pages with the slowest/most jarring loading-to-content transition
(the big grids, project detail, settlement cockpit) — not a mechanical
find-replace of every "Loading..." in the app, several of which are
genuinely instantaneous enough that a skeleton would just flicker.

### 4.11 The step-up (MFA) prompt
Currently: a step-up is triggered server-side (`StepUpRequiredError`) and
handled by a redirect to Keycloak's own OTP re-entry page — there is no
in-app "prompt" component today, the step-up *is* leaving the app briefly
for Keycloak's own UI (by design — this app never collects an OTP code
itself). Phase 4's job here is narrow: make the *return* experience
clear — after a successful step-up redirect-back, the action that
required it should visibly complete (already true per Phase 0/2's tested
settlement-approval flow) and, new, a brief inline notice
("Verifying..." while the redirect resolves) so the moment between
"Keycloak redirected back" and "the action actually completed" isn't a
silent gap. This is a small, targeted addition on the 2–3 pages that
trigger step-up (Settlement approve/reject, RFQ dispatch), not a new
general-purpose "step-up modal" — there is nothing to show *before*
redirecting (Keycloak's own page is the step-up UI).

## 5. Layout targets

- **1440px and 1280px are primary** — every page's main content area
  targets these widths without horizontal scroll or awkward wrapping.
  Sidebar 240px + content `max-w` none (fluid) but with sensible internal
  `max-w` on prose-like sections (empty states, help text) to avoid
  unreadably long lines.
- **1024px must stay usable** — sidebar collapses to icon-only (labels in
  a tooltip on hover/focus) at this width; the drawing split view
  (`TakeoffViewerPage.tsx`) and any bid-leveling matrix keep both panes
  visible but narrower, never one pane pushed fully off-screen.
- The drawing split view and big grids (BOQ reconciliation, bid-leveling)
  **must stay fast** — the 5,000-row test is the hard gate; any Phase 4
  styling change to `TakeoffViewerPage.tsx` or a grid page re-runs that
  benchmark before being considered done.
- No specific target below 1024px — this is an internal desktop tool used
  during working sessions at a desk, not a field/mobile app (confirmed:
  nothing in the SRS or brief asks for phone-width support here, unlike
  the generic `artifact-design`-style guidance for public web content).

## 6. Accessibility

- Full keyboard navigation: every interactive element reachable via Tab,
  in visual order, with a visible focus ring (`focus:ring-2
  focus:ring-brand focus:ring-offset-1` — replacing browser-default
  outlines inconsistently suppressed by Tailwind's preflight in a few
  places today).
- Every form input has a real `<label htmlFor="...">` (or `aria-label` for
  a genuinely label-less icon-button/search box) — several current inputs
  rely on `placeholder` alone, which is not a label and disappears on
  focus/input; found and fixed page-by-page during this phase, not a
  blanket search-replace (each input's correct label text needs the page's
  own context).
- Custom widgets (the taxonomy tree's expand/collapse, `Modal`'s dialog)
  get correct ARIA: `role="dialog" aria-modal="true"` (already on `Modal.tsx`),
  `aria-expanded`/`aria-controls` on tree expand/collapse toggles (currently
  missing — a Phase 4 fix on `TaxonomyAdmin.tsx`), `role="alert"` on inline
  mutation-error text so a screen reader announces it without the user
  needing to find it.
- AA contrast: every token in §2.1 was chosen to hit 4.5:1 minimum as
  *text*, not just as a fill behind white text — verified against both a
  white (`#FFFFFF`) and the app's `bg-slate-50` surface.
- `prefers-reduced-motion`: the new `Spinner` and any `animate-pulse`
  skeleton respect it (`motion-reduce:animate-none`, falling back to a
  static state) — small addition, not a broad animation system to audit
  (this app has almost no animation today beyond `transition-colors`,
  which doesn't need a reduced-motion guard).
- `@axe-core/playwright` (MIT) run on every page as part of this phase's
  QA, per the brief — no serious/critical violations. Findings get fixed
  as part of that page's own Phase 4 pass, not batched into a separate
  cleanup step.

## 7. What this phase does NOT do

- No dark theme (optional per the brief; not built this pass — light-only
  is a real, valid deliverable, and no reliable way exists to test a dark
  theme without a human looking at it, unlike everything else in this
  brief which has an automatable check).
- No new interaction patterns beyond what's listed above (no global toast
  system, no new modal *type* beyond what Phase 3 already built, no drawer)
  — Phase 4 is a restyle + accessibility + the specific new small
  components named above (`Badge`, `Spinner`, `Skeleton`), not a feature
  phase.
- No AG Grid Enterprise, no new paid/GPL/AGPL dependency of any kind —
  `@fontsource/ibm-plex-sans` (MIT) is the only new dependency this phase
  adds.

# Figma implementation plan — BankDash UI kit → InstallTec Estimating

**Status: PLAN ONLY. No file under `frontend/` has been edited.** Implementation
starts only after the drawing-pipeline-resilience run has merged (it currently
touches `frontend/src/features/drawings/api.ts` and
`frontend/src/pages/SheetIndexPage.tsx`, both of which this plan also touches).

**Decisions D1–D7 are resolved — see §8.** Summary: keep IBM Plex Sans (no font
change); comfortable + dense table variants; 100px/80px header; omit
search/gear/bell; no charts; `lucide-react`; no Account page.

Sources read: `docs/ui-design-system.md`, `docs/ui-qa-report.md`,
`docs/ui-qa/coverage.md`, `frontend/src/{index.css,App.tsx,app/AppShell.tsx,
components/Badge.tsx,features/boq/BoqReconciliationGrid.tsx}`, and the Figma file
via the Figma MCP (`get_metadata`, `get_variable_defs`, `get_screenshot`,
`get_design_context` on the sidebar, header, Loans and Settings-1 frames; pixel
values marked *sampled* were read from the rendered frame screenshots).

---

## 0. What this Figma file actually is (read this first)

The file is **BankDash — a retail-banking dashboard UI kit** (one Figma page,
"😍 Design", plus a cover page). It is not an estimating/procurement design, so
the mapping is **a visual language transfer, not a screen-for-screen port**.

| Set | Frames | Size |
|---|---|---|
| Desktop | Main Dashboard `78:351`, Transaction `105:0`, Accounts `101:0`, Investments `104:60`, Credit Cards `101:371`, Loan `101:677`, Services `112:941`, Setting Page 1/2/3 `112:279`/`112:504`/`112:699` | 1440 wide |
| Tablet | the same 10, e.g. Dashboard for Tab `147:4`, Transaction for Tab `150:111` … | 1024 wide |
| Mobile | the same 10, `169:3352` … `201:2` | 375 wide |

- **Mobile is out of scope** (`ui-design-system.md` §5: internal desktop tool, no
  target below 1024). 10 frames ignored.
- **Tablet (1024) frames are useful**: they keep the full ~230px sidebar (no
  icon-collapse) and a ~85px header, and reflow the dashboard cards. This
  agrees with our 1024 "must stay usable" target.
- The file has **no Figma variables/styles for colour, radius or spacing** apart
  from 8 named styles (below); everything else is raw fills. Tokens in §1 were
  therefore extracted from node fills and confirmed against screenshots.
- No Code Connect mappings and no component library exist in the file (nothing
  to reuse via Code Connect).

---

## 1. Design tokens: Figma → our Tailwind v4 `@theme`

Legend: **KEEP** (existing token already right) · **CHANGE** (existing token
gets a new value) · **NEW** (token doesn't exist yet) · **DEVIATE** (Figma value
deliberately *not* used, because it fails WCAG AA — see §1.6).

### 1.1 Colour

| Figma value | Where it's used in Figma | Ours today | Action |
|---|---|---|---|
| `#1814F3` | active nav text + 6px bar, primary buttons ("Save", "Send"), active tab + underline, bar-chart series 1, pagination active | `--color-brand: #1D4ED8` | **CHANGE** `--color-brand` → `#1814F3` (white-on-brand 8.63:1, brand-on-white 8.63:1 — *better* than today's 6.7:1) |
| ~darker `#1814F3` | (no hover state in Figma) | `--color-brand-hover: #1E40AF` | **CHANGE** → derived, e.g. `#120FC4`; must be measured ≥ 7:1 on white before commit |
| `#2D60FF` ("Primary 3") | dashboard active nav text, chart accent | — | **NEW** `--color-accent` (4.97:1 on white, 4.63:1 on `#F5F7FA` — usable as text, marginal) |
| `#EFF6FF` etc. | — (Figma has **no** tinted active-row/nav background) | `--color-brand-subtle: #EFF6FF` | **KEEP** (still used for selected rows/badges; the sidebar's active state changes to the Figma bar treatment, §3.1) |
| `#F5F7FA` | page/canvas background, search-pill fill | pages use white/`slate-50` | **NEW** `--color-canvas` |
| `#FFFFFF` | every card, header, sidebar | `bg-white` | **KEEP** (`--color-surface`, alias) |
| `#343C6A` ("Primary 2") | page title (28px), navy chart slice | `text-slate-800` | **NEW** `--color-ink-title` |
| `#333B69` | section headings (22px) | `text-slate-800` | **NEW** → collapse into `--color-ink-title` (1 step apart, indistinguishable) |
| `#232323` | body/table text | `text-slate-700/800` | **NEW** `--color-ink` |
| `#4F4F4F` ("text\|dark") | secondary body | `slate-600` | **NEW** `--color-ink-2` (8.19:1 ✔) |
| `#718EBF` | table headers, subtitles, captions, input text, icon strokes | `slate-500/600` | **DEVIATE for text** (3.32:1 ✘) → text uses `--color-muted` `#4F6FA5` (5.06:1 white / 4.72:1 canvas ✔). `#718EBF` kept **only** as border/icon colour (`--color-outline`, 3.32:1 ✔ for 1.4.11) |
| `#8BA3CB` | search placeholder | — | **DEVIATE** (2.56:1 ✘) → `--color-muted` |
| `#B1B1B1` | inactive nav label + icon | `slate-600` | **DEVIATE** (2.14:1 ✘) → `--color-muted` text, `--color-outline` icon |
| `#E6EFF5` | sidebar/header hairlines, table header rule | `slate-200` | **NEW** `--color-hairline` (decorative; no contrast requirement) |
| `#F2F4F7` | table row dividers | `slate-100` | **NEW** `--color-row-rule` (decorative) |
| `#DFEAF2` | input border | `slate-300` | **DEVIATE** (1.22:1 ✘ vs 3:1 required by 1.4.11 for input boundaries) → `--color-outline` `#718EBF` |
| `#FE5C73` ("Secondery") | negative amounts, notification bell, "Total" row, pink series | `--color-danger: #DC2626` | **KEEP** danger; Figma red becomes **NEW** `--color-negative-fill` `#FE5C73` (fills/icons/chart only; **3.0:1 — never text**). Negative-amount *text* stays `danger`/`text-red-700` |
| `#16DBCC` *(sampled)* | positive amounts, "Deposit" series, toggle-on, selected bar | `--color-success: #059669` | **KEEP** success; teal → **NEW** `--color-accent-teal` (fills/charts/toggle only; **1.74:1 — never text**). Positive-amount text stays `text-emerald-700` |
| `#FFBB38`/`#FCAA0B` *(sampled)* | yellow chart series, yellow icon | `--color-warning` | **NEW** `--color-chart-amber` (chart only) |
| `#FC7900`, `#FA00FF`, `#343C6A` *(sampled)* | pie slices | — | **NEW** chart palette only if we ever build a pie (see §5) — **not** added to `@theme` by default |
| tile pastels `#FFF5D9`, `#E7EDFF`, `#FFE0EB`, `#DCFAF8` *(sampled)* | 70px round icon tiles on stat cards | `*-subtle` tokens | **NEW** `--color-tile-{amber,blue,pink,teal}` (decorative behind an icon that itself meets 3:1) |
| card gradient `#4B48ED → #1612F4` *(sampled)* | credit-card visuals | — | **DROPPED** — banking-specific, and `ui-design-system.md` §1 forbids gradients |
| Shadow 1 `#E7E4E8CC` (4,4,18,-2) | one floating control only; **cards in the frames have no shadow** | flat, L0/L1 | **KEEP** flat. Do not add shadow to cards (matches both the Figma frames and `ui-design-system.md` §2.5) |

Semantic status colours (`success/warning/danger/info` + `-subtle`) and the
`Badge` tone map are **unchanged**: Figma has no badge/status component, only
red/teal amount colouring.

### 1.2 Typography

| | Figma | Ours today | Action |
|---|---|---|---|
| Family | Inter (all text) + "Mont Heavy DEMO" for the wordmark | IBM Plex Sans via `@fontsource/ibm-plex-sans` | **KEEP IBM Plex Sans (D1 resolved).** Figma's Inter is not adopted, so the Phase 4 font decision stands and `ui-design-system.md` §2.2 needs no font change. Sizes/weights/colours below still follow Figma. "Mont Heavy DEMO" is a demo-licensed font — **never bundle it**; wordmark is set in IBM Plex Sans 700. |
| Page title | 28 / 600, `#343C6A` | `text-xl` (20/28) | **CHANGE** → token `text-page-title` 28/600 |
| Section heading | 22 / 600, `#333B69` | `text-lg` (18) | **CHANGE** → `text-section` 22/600 (dense pages may use 18 — see D2) |
| Nav label / button | 18 / 500 | 14 / 500 | **CHANGE** nav to 16/500 (18 is too wide for our longer labels — "Procurement", "Cost library"), button 16/500 |
| Body / table cell | 16 / 400 `#232323` | 14 / 400 | **DEVIATE for dense tables** (D2): comfortable tables 16, dense tables/AG Grid stay 14/13 |
| Table header | 16 / 500 `#718EBF` | 14 / 500 slate-500 | **CHANGE** colour → `--color-muted`; size follows table density |
| Input / search text | 15 / 400 | 14 | **CHANGE** → 15 |
| KPI value | 20 / 600 `#232323` (label 16/400 muted) | — | **NEW** `text-kpi` |
| Tabular figures | not specified in Figma | required by design-system §2.2 | **KEEP** `tabular-nums` on every number |

Figma line-height is "100%/normal"; we keep our 1.4–1.5 rule.

### 1.3 Spacing / layout (measured from frames)

| Element | Figma | Ours | Action |
|---|---|---|---|
| Canvas | 1440 wide; sidebar 250 + content 1190 | sidebar `w-60` (240) | **CHANGE** sidebar → 250 at ≥1280 |
| Content gutter | 40px each side (`x=290` in 1190 area), 30px card inner padding, 24px gap between cards | `p-6` (24) | **CHANGE** page padding → 40 (`px-10`) at ≥1280, 24 at 1024 |
| Header | 100px tall, white, 1px `#E6EFF5` rule (tablet: ~85) | `h-14` (56) | **CHANGE** → 100 at ≥1280 / 80 at 1024 (**DECISION D3**: costs ~44px vertical on dense pages) |
| Sidebar row pitch | 64px, icon 25px, label at x=95 | `py-1.5` (~32) | **DEVIATE**: we have up to 15 role-gated items vs Figma's 8 → pitch 44px, icon 24px, so the sidebar fits 768px tall without scrolling |
| Stat cards | 255×120, 25px radius, 70px icon tile | — | **NEW** `StatCard` |
| Table row | 65px pitch (comfortable) | ~37px (`py-2`) | comfortable variant 56–65px; dense variant unchanged |

### 1.4 Radius

| Figma | Ours | Action |
|---|---|---|
| **25px** cards / table containers | `rounded` 4px / `rounded-lg` 8px | **CHANGE** → `--radius-card: 25px` (`rounded-card`) |
| **15px** inputs, "Save" button | `rounded` 4px | **CHANGE** → `--radius-control: 15px` |
| **50px** outlined pill buttons ("Repay", "Download", "View Details") | `rounded` | **CHANGE** → `--radius-pill` for *secondary* buttons |
| **40px** search pill | — | **NEW** (only if a search exists — D4) |
| 10px on active-nav bar, tab underline | — | **NEW** `--radius-bar: 10px` |
| circles: icon tiles (70px), avatars, header icon buttons (50px) | "never `rounded-full` except avatars" | **CHANGE** rule: allowed for icon tiles/avatars/icon buttons; still **not** for `Badge` (keeps a small radius) |
| Modals | `rounded-lg` | no Figma modal exists | **DECISION** default: use `--radius-card` |

`ui-design-system.md` §2.4 is superseded by this table; that doc must be updated
in the same PR as the token change.

### 1.5 Proposed `@theme` delta (illustrative — final hexes measured at implementation)

```css
@theme {
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;   /* unchanged (D1) */

  --color-brand: #1814F3;            /* was #1D4ED8 */
  --color-brand-hover: #120FC4;      /* derive + measure */
  --color-accent: #2D60FF;
  --color-canvas: #F5F7FA;
  --color-ink: #232323;
  --color-ink-2: #4F4F4F;
  --color-ink-title: #343C6A;
  --color-muted: #4F6FA5;            /* AA text stand-in for Figma #718EBF */
  --color-outline: #718EBF;          /* borders/icons only, 3.3:1 */
  --color-hairline: #E6EFF5;
  --color-row-rule: #F2F4F7;
  --color-negative-fill: #FE5C73;    /* fill/icon/chart only */
  --color-accent-teal: #16DBCC;      /* fill/toggle/chart only */
  --color-tile-amber: #FFF5D9; --color-tile-blue: #E7EDFF;
  --color-tile-pink: #FFE0EB;  --color-tile-teal: #DCFAF8;

  --radius-card: 25px; --radius-control: 15px; --radius-pill: 50px; --radius-bar: 10px;
}
```

### 1.6 WCAG AA reconciliation (why we deviate from Figma in places)

Measured contrast (WCAG formula, on `#FFFFFF` / `#F5F7FA`):

| Figma colour | Use | Ratio | Verdict |
|---|---|---|---|
| `#1814F3` | text/fill | 8.63 / 8.04 | ✔ better than current brand |
| `#343C6A`, `#333B69`, `#232323`, `#4F4F4F` | text | ≥ 7.6 | ✔ |
| `#2D60FF` | text | 4.97 / 4.63 | ✔ (thin margin on canvas) |
| `#718EBF` | text | 3.32 / 3.09 | ✘ text · ✔ border/icon (≥3:1) |
| `#8BA3CB` | placeholder | 2.56 / 2.39 | ✘ |
| `#B1B1B1` | inactive nav | 2.14 / 2.00 | ✘ |
| `#FE5C73` | text | 3.00 / 2.80 | ✘ text |
| `#16DBCC` | text | 1.74 / 1.63 | ✘ text |
| `#DFEAF2` | input border | 1.22 | ✘ (1.4.11) |
| `#4F6FA5` (our `--color-muted`) | text | 5.06 / 4.72 | ✔ |

Every ✘ above is a place where a pixel-exact Figma port would break the axe
suite (or 1.4.11, which axe does not test but AA requires). The rule from
`ui-design-system.md` §2.1 stands: **success/negative/teal are fill-icon-chart
colours; text uses the tinted `Badge` pairing or `text-emerald-700`/`text-red-700`.**
The visual difference from Figma is small (a slightly deeper blue-grey for
secondary text; darker input outlines).

---

## 2. Figma frame → existing page/route/component mapping

Because the kit is banking-specific, only **shell** and **generic patterns**
map. "Pattern" = we reuse the frame's layout/visual grammar for an existing page.

| Figma frame | Maps to | Route | Mapping quality |
|---|---|---|---|
| **App shell** (sidebar + 100px header, on every frame) | `AppShell.tsx` | all | **Direct** — see §3.1 |
| **Main Dashboard** "Overview" (stat/card grid + chart cards + list card) | `HomeDashboardPage` | `/dashboard` | **Pattern**. Our page is 4 role-gated *worklist tiles* (Approvals, Quarantine, Vendor duplicates, Expiring certs) with no charts. Restyle tiles as 25px white cards on `#F5F7FA` with `StatCard`-style header + list rows. **No charts added** (no data source; see §5) |
| **Transaction** (tabs "All/Income/Expense" + comfortable table + numbered pagination) | Table-with-tabs pattern: `AuditPage` (list), `VendorsPage`, `CostLibraryPage`, `QuoteReviewPage` (status tabs if any), `ProjectsListPage` | `/audit`, `/vendors`, `/cost-library`, `/` | **Pattern** — `TabBar`, comfortable `Table`, `Pagination`. `ProjectsListPage` has no real pagination today (UI-P2-006) → the Figma Pagination component is the natural fix but is a **feature change** (needs server paging) — flagged, not silently done |
| **Accounts** (4 stat cards → list card + chart card + side card) | `ProjectDetailPage` (project overview: status, members, drawings), `VendorDetailPage` header | `/projects/:id`, `/vendors/:id` | **Pattern** — `StatCard` row for project metrics (drawing count, BOQ lines, package count — only if those counts are already in the payload; otherwise no stat row) |
| **Investments** (3 stat cards → 2 chart cards → list + table) | `ModuleEPage` (post-award: contracts / revisions / variations / outturn — 4 tabs, read-only) | `/projects/:id/module-e` | **Pattern** for stat row + list/table cards. Charts optional (see §5) |
| **Loan** (4 stat cards → big "Active Loans Overview" table with totals row + pill action buttons) | `SettlementPage`, `BidLevelingPage`, `ProcurementPackagesPage` | `/projects/:id/settlement`, `/procurement/bid-leveling`, `/procurement/packages` | **Pattern** — stat-card row + table card + red "Total" row + outlined pill row-actions. **Highest-value frame for us**, but our tables are far denser (D2) and the settlement draft has sliders/step-up that Figma doesn't cover |
| **Services** (3 feature cards → list of rows with icon tile + 4 text columns + pill "View Details") | `VendorsPage`, `CostLibraryPage` (list rows → detail), `TypologyPage` cluster list | `/vendors`, `/cost-library`, `/projects/:id/typology` | **Pattern** — `ListRow` card with icon tile |
| **Credit Cards → "Add New Card" form + "Card Setting" list** | Create/edit forms: `BoqImportWizardPage`, `ExportPage`, `WinLossPage` (record outcome), New-project form on `ProjectsListPage`, add-vendor/add-rate forms | various | **Pattern** — form grammar: 16px label above 50px-tall 15px-radius input, 2-column grid, primary button bottom-left |
| **Setting 1/2/3** (Edit Profile · Preferences · Security tabs, big form card, toggles) | `AdminPage` (six tabs) form grammar; **not** a profile page | `/admin` | **Pattern only** for tabs + form card + toggle. **The profile/password/2FA content itself has no counterpart and must not be built** (§4) |
| **Dashboard/…/Setting for Tab** (1024) | our 1024 layout target | all | **Direct** reference for 1024: full sidebar retained, header ~85 |

### Coverage of our 26 pages (from `docs/ui-qa/coverage.md` + `App.tsx`)

Restyle every page through the shared components below; the Figma frame that
guides each:

| Our page / route | Guiding Figma frame | Notes |
|---|---|---|
| `ProjectsListPage` `/` | Transaction (table+tabs) / Services (rows) | pagination is a feature gap |
| `HomeDashboardPage` `/dashboard` | Main Dashboard | tiles → cards, no charts |
| `ProjectDetailPage` `/projects/:id` | Accounts | + drawing upload, members, remove-member modal keep behaviour |
| `SheetIndexPage` `…/drawings/:did` | Services (rows) | **conflicts with other run** — restyle last |
| `TakeoffViewerPage` `…/sheets/:idx` | **none** | split PDF/DXF viewer; only shell + control styling; must not change layout mechanics (perf) |
| `TypologyPage` | Services (rows) + Setting tabs | keep confirm/reject gating |
| `BoqImportWizardPage` | Credit Cards "Add New Card" form | stepper is ours; only field/button grammar reused |
| `BoqReconciliationPage` + `BoqReconciliationGrid` | Loan (table card) — **container only** | AG Grid keeps dense rows (§6) |
| `ProcurementPackagesPage` | Loan / Services | dispatch = step-up; unchanged |
| `QuarantineQueuePage` `/inbox` | Transaction | platform_admin "Resolve tenant" gate unchanged |
| `QuoteReviewPage` | Loan | dense table variant |
| `BidLevelingPage` | Loan | dense; no-empty-state gap (UI-P2-017) can be closed with the new empty-state |
| `SettlementPage` | Loan + Setting (tabs/toggles for scenarios) | SoD + step-up untouched |
| `ExportPage`, `WinLossPage` | Credit Cards form | reason-codes form |
| `AdminPage` (6 tabs) | Setting tabs + form card | md/admin gating unchanged |
| `AuditPage` | Transaction (table+tabs+pagination) | verify-chain md-only unchanged |
| `VendorsPage`, `VendorDetailPage`, `VendorDuplicatesPage` | Services / Accounts | |
| `CostLibraryPage`, `CostItemDetailPage` | Services / Investments table | |
| `ModuleEPage` (4 tabs) | Investments | |
| `NotFoundPage`, `PlaceholderPage`, `LoginPage` (unused) | — | see §4 |

---

## 3. Components to build or change

### 3.1 Change (existing)

| Component | Change |
|---|---|
| `AppShell.tsx` | Sidebar 250px; Figma active-state = 6px left bar (`--radius-bar` on right corners) + brand text (replaces `bg-brand-subtle` fill + `border-l-2`); inactive = `--color-muted`; icon per item; header 100/80px with **page title in the header** (see below). **`filterVisibleNavItems`, `requiresRoles`, the `end` logic and the platform_admin Inbox exception are copied verbatim — no gating logic moves.** `AppShell.test.tsx` must pass unmodified. |
| `Badge.tsx` | Tone classes unchanged (AA-verified); only radius/size tweak if any. |
| `Modal`, `ConfirmModal`, `TextPromptModal` | Radius → card token; primary button → new `Button`. Focus-trap/`role=dialog` untouched. |
| `Spinner`, `Skeleton` | Stroke/colour to new brand; keep `motion-reduce`. |
| `BoqReconciliationGrid` `themeQuartz.withParams` | `accentColor`→brand, `headerTextColor`→`--color-muted`, `headerBackgroundColor`→`#F5F7FA`, `rowHoverColor`→`#F5F7FA`, `fontFamily` unchanged (IBM Plex Sans), **`fontSize`/row height/virtualization unchanged**. Container gets the 25px radius via a wrapper. |
| `index.css` | §1.5 tokens + font import swap. |
| 27 files using `bg-blue-*`/`bg-brand`/`text-brand`, ~all pages using `slate-*` | Migrated to tokens **per page** as each page is restyled (not a blanket find/replace). |

**Page title placement.** Figma puts the title (28px) in the header. Today each
of the 26 pages owns its own `<h1>`. Plan: a `<PageTitle>` component that
**portals the real `<h1>` into a header slot** — one `<h1>` per page is
preserved (axe `page-has-heading-one`), pages keep ownership of their title,
and `getByRole('heading', …)` in existing e2e specs keeps working. No router
change.

### 3.2 New (shared, in `src/components/`)

| Component | From Figma | Notes |
|---|---|---|
| `Button` (`primary` 15px radius solid brand · `secondary` 50px-pill outlined · `destructive` outlined red) | "Save", "Send", "Repay", "Download", "View Details" | Replaces inline button classes. `focus-visible` ring kept. Pending state uses `Spinner` (already required by design doc §4.2). Must forward `disabled` + `title` exactly (SoD "Awaiting a different approver" relies on disabled buttons) |
| `Card` (25px, white, no shadow, 30px pad) + `SectionHeading` (22/600, optional "See All" link) | every panel | |
| `StatCard` (70px round tile in `--color-tile-*` + label + KPI) | Accounts/Loans/Investments | value uses `tabular-nums` + `formatMoney` |
| `TextField`/`SelectField`/`Textarea` (label above, 50px, 15px radius, `--color-outline` border, brand focus ring) | Setting/Card forms | **must** render a real `<label htmlFor>` (AA rule) — Figma's floating placeholders are not labels |
| `Toggle` (56×32 switch, teal-on) | Preferences | Only if a screen needs one (Admin "active" toggles). Must be `role="switch"` + `aria-checked`; on-state contrast of the thumb/track pair to be measured (teal track is 1.74:1 vs white — fails 1.4.11 unless the thumb/edge carries the state → add a 2px `--color-outline` ring or use brand for on) |
| `TabBar` (16/500, 3px brand underline, `--radius-bar`) | Transaction/Setting | `role="tablist"`, arrow-key nav; replaces `AdminPage`/`ModuleEPage`/`TypologyPage` ad-hoc tabs. Existing e2e locate tabs by role+name — keep names |
| `Table` primitives (`comfortable` / `dense` variants) | Transaction/Loan | header muted 500, `--color-row-rule` dividers, optional totals row, `tabular-nums` right-aligned numerics. **Dense = today's metrics.** |
| `Pagination` (Previous · numbered · Next, active = brand pill) | Transaction | Presentational only; wiring to server paging is a separate change |
| `ListRow` (icon tile + N columns + trailing pill action) | Services/Investments | |
| `IconButton` (50px circle `#F5F7FA`) | header gear/bell | |
| `Avatar` (initials, circle) | header avatar | **No photos.** Initials from `user.username` |
| `Icon` set (see §7) | sidebar + tiles | bundled |
| `EmptyState` | (not in Figma) | ties to design-system §4.9 |

---

## 4. Figma screens with no matching page, and our pages with no Figma screen

### 4.1 Figma screens/elements with **no** counterpart in our app

| Figma | Why it doesn't map | Recommendation |
|---|---|---|
| **Credit Cards** (card visuals, card list, expense donut, Add-card, Card settings: block card/PIN/Google Pay/Apple Pay) | Banking domain | **Not built.** Reuse only the form + list-row grammar |
| **Loans** (loan tiles, "Repay") | Banking domain | Table/stat grammar only |
| **Investments** (stock list, "Trending Stock", yearly/monthly line charts) | Banking domain | Grammar only; charts see §5 |
| **Services** ("Bank Services", Life Insurance…) | Banking domain | Row grammar only |
| **Quick Transfer** (contact avatars + amount + Send) | No payments | Not built |
| **My Cards** carousel + card gradient | No cards; gradients forbidden by design system | Not built |
| **Weekly Activity / Balance History / Expense Statistics** charts | No chart library, no data endpoints, no chart in any page today | **DECISION D5** (default: not built) |
| **Setting → Edit Profile** (name, DOB, address, photo upload) | Identity lives in Keycloak; app has no user-profile resource (`/auth/me` returns username/roles only) | **Not built.** Optional read-only "Account" panel (username, roles) if wanted |
| **Setting → Preferences** (currency, time zone, notification toggles) | No user-preference storage or notification system | **Not built** |
| **Setting → Security** (2FA toggle, change password) | **Must not be built**: password/OTP are collected only by Keycloak; `DEV_DISABLE_MFA`/step-up is server-controlled; an in-app 2FA switch would contradict the step-up/MFA model | **Explicitly excluded** |
| **Header search** ("Search for something") | No global search endpoint | **DECISION D4**: default omit (a control that does nothing fails a11y/UX). Optional: client-side "jump to project" over the already-fetched project list |
| **Header gear + bell** | No settings page; no notification service | Default omit. Bell could later link to `/dashboard` (the worklist *is* our notification surface) |
| **Avatar photo** (`pexels-…` image) & wordmark font | Remote/licensed assets | Replaced by initials avatar and an IBM Plex Sans wordmark |
| **Mobile frames (10)** | Out of scope | Ignored |

### 4.2 Our pages/features with **no** Figma screen (designed from the kit's grammar)

`TakeoffViewerPage` (drawing split view: PDF.js/DXF canvas + calibration/override
controls), `SheetIndexPage`, `BoqImportWizardPage` (multi-step), `BoqReconciliationPage`
(5,000-row grid), `QuoteReviewPage`, `BidLevelingPage` (matrix), `SettlementPage`
(sliders, scenarios, submit/approve with step-up), `ExportPage`, `WinLossPage`,
`QuarantineQueuePage`, `TypologyPage`, `AdminPage` sub-tabs (taxonomy tree,
policies, tolerances, layer-trade mapping, reason codes, service regions),
`AuditPage` (+ hash-chain verify), `VendorDuplicatesPage`, `CostItemDetailPage`,
`ModuleEPage` contract views, and all **modals** (Modal/Confirm/TextPrompt),
**empty states**, **skeletons**, **step-up "Verifying…" notice**, **DevMfaBanner**,
`NotFoundPage`. None of these has a Figma frame; they get the tokens + shared
components only, and nothing about their behaviour changes.

Recommendation: since there's no design for these, **we can't claim Figma
fidelity for them** — the acceptance criterion is "uses the tokens and shared
components, passes the same tests," not pixel parity.

---

## 5. Charts (D5 resolved: none this run)

The kit is chart-heavy (bar, pie, line/area). We have **no chart library and no
page with a chart**. Adding one is a new dependency + new data endpoints, i.e.
a feature, not a restyle. **Default: no charts in this run.** If wanted later:
hand-rolled inline SVG (no dependency), using the sampled series colours,
each chart requires a data-table alternative and non-colour cues (teal-vs-blue
alone fails 1.4.1).

---

## 6. Constraints — how each is preserved

**Air-gapped**
- Fonts: `@fontsource/ibm-plex-sans` (already installed, unchanged) imported in CSS and bundled by Vite. No `<link>`, no Google Fonts, no "Mont" demo font, no new font dependency.
- Icons: bundled (§7). No icon-font CDN.
- Images: **zero** Figma asset URLs in code (they're 7-day remote URLs). Avatar = initials; logo = a committed local SVG/wordmark; card/pexels imagery not used.
- CI guard (new, cheap): add a vitest/grep check that fails if `src/` or built `dist/` contains `figma.com`, `fonts.googleapis`, `fonts.gstatic`, or any `https?://` asset reference.

**WCAG AA / axe 18/18** (`phase4-accessibility.spec.ts`: Projects, ProjectDetail, SheetIndex, Vendors, Typology, CostLibrary, ProcurementPackages, Quarantine, QuoteReview, BidLeveling, Export, WinLoss, Settlement, BoqReconciliation, Admin×6 tabs, Audit, ModuleE×4 tabs, HomeDashboard)
- Colour deviations in §1.6 are mandatory, not stylistic.
- 1.4.11: input/toggle/button boundaries ≥3:1 via `--color-outline`.
- Focus ring (`focus-visible:ring-2 ring-brand ring-offset-1`) kept on every new control; icon-only buttons get `aria-label`.
- Nav landmarks: single `<nav>`, `<header>` banner, `<main>`; portalled `<h1>` inside banner is valid.
- Sequencing: **restyle in the same order as the a11y spec and run axe after each page group**, not at the end (repeats the Phase 4 method that caught `text-success` at 3.76:1).

**5,000-row grid performance**
- Only Theming-API *colour/font* params and a wrapper radius change. No change to `rowHeight`, `rowBuffer`, column defs, virtualization, cell renderers, or `fontSize`.
- Do **not** add cell renderers (badges/icons/pill buttons) to the reconciliation grid as part of this work.
- Gate: `frontend/e2e/boq-reconciliation.spec.ts` (the 5,000-row benchmark) run before/after; record numbers in the PR; regression >10% blocks.
- Any change to `TakeoffViewerPage` re-runs the same gate (design-system §5).

**Role / step-up / SoD behaviour — exactly as is**
- No `requiresRoles`, `hasRole`, disabled-state, or server call is edited. Restyle PRs are className/markup-wrapper only; `Button` must preserve `disabled`, `title`, `type`, and `aria-*` passed by callers.
- Untouched behaviours explicitly regression-tested by existing suites: SoD ("Awaiting a different approver" disabled Approve/Reject for the submitter), step-up redirect + `step-up-freshness.spec.ts`, platform_admin Inbox exception, md/admin gating on Admin/Audit, estimator's server-granted Settlement access.
- Nothing is added that would let the UI *suggest* an action the role can't take; nothing is removed that currently hides one.
- Security Settings (password/2FA) intentionally **not** built (§4.1).

---

## 7. Icons (D6 resolved: lucide-react)

The kit's sidebar icons are multi-path Figma vector groups delivered as
short-lived remote SVG URLs. Two air-gap-safe options:

- **A (chosen, D6): `lucide-react`** — ISC licence, tree-shaken and bundled by Vite, ~15 icons needed (home, arrow-left-right, user, bar-chart, credit-card/receipt, hand-coins/scale, wrench, settings, bell, search, chevrons, download, plus…). Adds one dependency (design-system §7 currently says fontsource is the only one; needs your OK).
- **B (not chosen): hand-committed SVG components** (`src/components/icons/*.tsx`) — zero deps; either export the Figma icons once and commit them, or draw a small set. More work, exact-Figma look possible.

Either way icons are `aria-hidden` when paired with a text label and never the sole content of a control.

---

## 8. Decisions (resolved)

| # | Question | Decision |
|---|---|---|
| **D1** | Font | **Keep IBM Plex Sans** — no font change, no reversal of the Phase 4 decision |
| **D2** | Density | **Comfortable variant kept**, alongside dense: comfortable (Projects, Vendors, CostLibrary, Inbox, ModuleE); dense (BOQ, QuoteReview, BidLeveling, Settlement, Audit, and AG Grid unchanged). *Interpretation:* "keep the comfy variant" read as adopting my recommended two-variant split, not making every table comfortable — say so if you meant all tables |
| **D3** | Header height | 100px at ≥1280, 80px at 1024 |
| **D4** | Header controls | Omit search, gear, bell. Keep initials avatar + visible "Sign out" button |
| **D5** | Charts | None this run |
| **D6** | Icons | `lucide-react` (approved new dependency, ISC, bundled/tree-shaken; option B dropped) |
| **D7** | Account page | Not built |

Consequences: `ui-design-system.md` §7's "fontsource is the only new dependency"
is amended to add `lucide-react`; §2.2 (typography) keeps its font, only sizes change.

## 9. Implementation sequencing (after the other run merges)

0. **Precondition**: other run merged; rebase; `master` green (`tsc`, vitest 29/29, lint, `npm run e2e`, `e2e:real-backend`).
1. **Tokens + font + `Button`/`Card`/`TextField`/`TabBar`/`Table`/`StatCard`/`Icon`** (no page changes yet); unit tests; contrast check script over all text/bg token pairs (fail on <4.5 text, <3 non-text).
2. **AppShell** (sidebar, header, `PageTitle` portal, initials avatar). Gate: `AppShell.test.tsx` unchanged & green; `layout-widths.spec.ts` at 1440/1280/1024.
3. **Page groups**, each followed by its axe tests + affected e2e: (a) Projects, ProjectDetail, HomeDashboard; (b) Vendors ×3, CostLibrary ×2; (c) Admin, Audit, ModuleE; (d) BOQ import/reconciliation (+ grid theme, **5,000-row gate**); (e) Procurement, Quarantine, QuoteReview, BidLeveling; (f) Settlement, Export, WinLoss (**SoD/step-up specs**); (g) Typology, Takeoff, **SheetIndex last** (other-run conflict).
4. Update `docs/ui-design-system.md` (tokens, radius, type, header) in the same PRs; refresh `docs/ui-qa/screenshots/` for the layout-widths set.
5. Final: full `make test-all`, vitest, lint, build, `e2e`, `e2e:real-backend --workers=1`, `step-up-freshness`, axe **18/18**, air-gap grep guard, before/after 5,000-row numbers.

Estimated scope: ~26 pages restyled, ~10 new shared components, 0 backend changes,
0 role/permission changes.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Pixel-fidelity pressure vs AA | §1.6 table is the contract; show side-by-side once and get sign-off on the muted-blue deviation early |
| Merge conflict with the drawing-pipeline run (`SheetIndexPage.tsx`, `drawings/api.ts`) | Wait for merge; restyle SheetIndex last |
| Header/`PageTitle` portal breaks heading-based e2e/axe | Portal renders the real `<h1>`; prototype on one page + run axe before rolling out |
| Larger type + 25px cards reduce information density on Settlement/BOQ | D2 dense variant; screenshot-review at 1280×720 |
| Icon/sidebar overflow with 15 items | 44px pitch; nav already `overflow-y-auto`; verify at 1024×768 |
| Sampled hexes (tile pastels, teal, amber, gradient) are from rendered pixels, not Figma variables | Values are stable flat fills; re-sample if design changes |

# Company Brain — Design & UX Review + Instagram Launch Post
*Reviewed: 2026-06-23 · Reviewer: Claude Code (Sonnet 4.6)*

---

## PART A — DESIGN / UX REVIEW

### Visual Quality Verdict

The product ships in a strong state. The dark-mode glassmorphism palette (deep `#060708` black, frosted `rgba(255,255,255,0.04)` cards, luminous indigo/emerald/amber accents) is coherent, intentional, and not generic AI-slop. The design system is token-driven, avoids emoji headers, centered hero fluff, and fake stats — the numbers on screen come from real API calls with graceful fallbacks. Inter is clean; `clamp()`-driven type scale is disciplined. Both screenshots (v2, v3) confirm the visual direction executes as intended.

No major visual-system rewrites needed before launch. The issues below are surgical.

---

### AI-Slop Audit

| Pattern | Status | Notes |
|---|---|---|
| Generic rainbow gradients | Clear | Mesh blobs are subdued, single-palette |
| Emoji section headers | Clear | Pure Lucide icons throughout |
| "Centered everything" layout | Clear | Left-aligned type, proper bento grid |
| Fake/hardcoded stats as proof | Partial risk | See P0.4 — fallback data visible in demo mode |
| Lorem ipsum / placeholder copy | Clear | Fallback copy is realistic (Acme Corp, real workflow names) |
| Generic hero words ("powerful", "seamless") | Clear | Page copy is specific and technical |

---

### P0 — Fix Before Today's Launch

**P0.1 — Mobile nav: sidebar is completely absent below `lg` breakpoint**

The `Sidebar` component renders `hidden lg:block` — it simply does not exist on mobile. The `Header` opens a Sheet via a `Menu` button, and `SidebarNav` is shared. This is architecturally correct but has one problem: the mobile sheet has no close gesture other than clicking the overlay or a nav item. There is no `X` close button and no `aria-label` on the Sheet trigger that makes the current state ("open") discoverable. On small phones the full SidebarNav is 200-250px of content in a 72-width sheet; the "Two loops running" footer status widget may overflow on 360px-wide phones.

**Fix:** Add a visible close button inside the Sheet header, or confirm shadcn Sheet handles it. Verify the sheet renders correctly at 360px width.

**P0.2 — Reconciliation page: `window.prompt()` for audit reason is broken on mobile**

`reconciliation/page.tsx` line 89 uses `window.prompt()` to collect an optional reason string before releasing a quarantine. Native browser prompt dialogs are:
- Blocked in iOS Safari WKWebView (which is what PWA "Add to Home Screen" uses on iPhone)
- Non-existent in many PWA hosts
- Visually inconsistent with the design system

This is a direct functional regression for mobile PWA users: the "Dismiss" and "Accept synthesis" actions will silently fail or hang on iOS PWA mode.

**Fix:** Replace `window.prompt()` with an inline popover or an `AlertDialog` from shadcn. A small modal with a single `<textarea>` and Cancel / Confirm buttons takes ~30 lines and matches the existing design language exactly.

**P0.3 — No PWA manifest or service worker**

`public/` contains only the default Next.js scaffold SVGs (file.svg, globe.svg, next.svg, vercel.svg, window.svg). There is no `manifest.json`, no `apple-touch-icon`, and no service worker. The product ships as a "web app + installable PWA" per the brief, but nothing in the codebase enables installation. Browsers will not show an "Add to Home Screen" prompt, the app icon on the home screen will be a generic screenshot, and offline mode is non-functional.

**Fix (minimum viable PWA, ~2 hours):**
1. Create `public/manifest.json` with `name`, `short_name`, `start_url`, `display: "standalone"`, `theme_color: "#060708"`, `background_color: "#060708"`, and icon paths at 192x192 and 512x512.
2. Create `src/app/icon.png` and `src/app/apple-icon.png` (Next.js App Router auto-links these).
3. Add `<link rel="manifest" href="/manifest.json">` in layout (Next.js Metadata API: `manifest: "/manifest.json"` in `metadata` export).
4. For offline: add `next-pwa` or a minimal `public/sw.js` that caches the shell. Even a basic cache-first for the navigation routes removes the "white screen when API is down" experience.

**P0.4 — Fallback data in demo mode is too optimistic and could mislead**

`page.tsx` (Command Center) initializes with `FALLBACK_STATS` including `total_workflow_runs: 9`, `pending_review: 3`, `accumulated_cost_usd: 4.82`. The approvals page also starts with real-looking FALLBACK data. In demo mode these render exactly like live data. The `Header` shows "Demo Mode" status text, but only on `sm:` breakpoints and above — on mobile it's hidden (the status chip shows a dot but the label has `hidden sm:inline`).

This is not dishonest — it is intentional demo scaffolding — but for a public launch, first-time visitors will not know whether the dashboard they're seeing reflects real data or placeholder. The "Demo Mode" label must be visible at all screen sizes.

**Fix:** Remove `hidden` from the status label (let it show on all widths, even if abbreviated: "Demo" not "Demo Mode") or add a dismissible banner across the top when `status === "offline"`.

---

### P1 — Ship This Week

**P1.1 — Touch targets: Reconciliation action buttons are 30px tall on mobile**

The Dismiss / Accept synthesis buttons in `reconciliation/page.tsx` use `px-3 py-1.5 text-sm` which renders at approximately 30px height. Apple HIG and WCAG 2.5.5 recommend 44px minimum. On the approvals card the Approve / Reject / Modify buttons are full-width and fine; the reconciliation view is the outlier.

**Fix:** Change to `py-2.5` or `h-10` on the reconciliation action buttons.

**P1.2 — Audit log stepper overflows on mobile without visible scroll affordance**

`audit/page.tsx` renders the step pipeline as `flex overflow-x-auto pb-1`. Each step card is `min-w-[120px]` so 5 steps = 610px+ in a 375px viewport. The horizontal scroll works but there is no visual affordance (no shadow fade at the right edge indicating "more content right"). Users will not discover this on a phone.

**Fix:** Add a right-side gradient fade overlay over the step list container (`after:` pseudo-element, `from-transparent to-background`, pointer-events none) to signal scrollability.

**P1.3 — Onboarding: sidebar shows "Two loops running" before onboarding completes**

The sidebar footer status widget reads "Two loops running / Ingestion + Action active" even on the onboarding page where no loops are actually configured yet. A new user sees a claim that contradicts their experience (nothing is set up).

**Fix:** Conditionally suppress the sidebar status widget on the `/onboarding` route, or change it to "Ready to configure" during onboarding.

**P1.4 — Missing `not-found.tsx` and `error.tsx` design review**

These files exist in the file tree but were not inspected. Verify they use the same `glass-card` language and do not fall back to Next.js default error UI (white, unbranded).

**P1.5 — Light mode: glass cards need validation**

The screenshots are exclusively dark mode. Light mode (`--glass-bg: rgba(255,255,255,0.72)`) is coded but unverified in screenshots. The `mesh-1/2/3` blobs in light mode are very subtle (10% / 8% / 7% opacity) — verify they add depth rather than looking like a bug. The `StatTile` and `CalibrationChart` components in particular should be spot-checked in light.

---

### P2 — Polish Later

**P2.1 — Reconciliation empty state is perfectly clean but could be warmer**

The "No active conflicts. Knowledge is in sync." empty state is correct and technically honest (the spec comment in the code explicitly prevents false-positive "all good" messages when the API is unreachable — well done). The `CheckCircle2` icon and copy are fine. Optionally, surface when the last check ran to increase trust.

**P2.2 — Hub "Connectors" tab: toggles are decorative**

The `Switch` on each connector card is visually present but the `onChange` handler is absent — toggling it does nothing (there's no `onCheckedChange` prop in the code). For a public launch this is a visual lie. Either wire it to an API call, or replace the Switch with a static "Connected" badge.

**P2.3 — Settings page: no save action on the ProfileEditor**

The `ProfileEditor` component is imported but not visible in this review scope. Confirm it has a visible save/submit action and handles the loading/error state.

**P2.4 — `template.tsx` animation — verify no flash on first paint**

`app/template.tsx` wraps each page in an animation. Verify it does not produce a FOUC (flash of unstyled or invisible content) on the initial page load, particularly when the dark theme is applied via `next-themes`.

---

### Mobile Responsiveness Summary

| Surface | Mobile Status |
|---|---|
| Header / hamburger nav | Works; Sheet opens correctly. Close UX is thin. |
| Sidebar | Desktop only (correct). No mobile leak. |
| Command Center bento | `grid-cols-2` on sm, `xl:grid-cols-4` stat row. Good. |
| Approval Queue | `lg:grid-cols-[1fr_300px]` stacks to single column. Good. |
| Reconciliation list | `flex-col sm:flex-row` responsive. Button tap targets too small. |
| Audit timeline | Stepper overflows horizontally. Missing scroll affordance. |
| Onboarding | `max-w-2xl mx-auto`. Works on phone; input and buttons are appropriately sized. |
| Settings | `lg:grid-cols-2`, stacks on mobile. Fine. |

---

## PART B — INSTAGRAM LAUNCH POST

### Visual Direction

**Palette:** Match the product's dark mode exactly. Background: `#060708` (near-black). Ambient mesh: two soft radial blobs — deep indigo (`#3730a3` at 20% opacity) top-right, emerald (`#059669` at 10% opacity) bottom-left. This echoes the CSS `--mesh-1/2/3` variables.

**Glass card motif:** A single frosted panel centered in the frame. `rgba(255,255,255,0.05)` fill, `1px solid rgba(255,255,255,0.08)` border, `border-radius: 20px`. Inside it, show the Approval Queue card (Customer Retention / CriticAgent flagged / Approve + Reject buttons) cropped to fill the card at ~65% of image width.

**Typography:** Inter SemiBold for headlines, Inter Regular for subhead. White (#F4F4F6) for headline, muted slate (#8A8F98) for subhead. No emoji. No gradient text.

**Logo / brand mark:** Top-left: a 40x40 `border-radius: 12px` square filled `#2563eb` (accent-blue) containing the Lucide Brain icon in white, followed by "Company Brain" in 15px Inter SemiBold, "Autonomous Operations" in 11px muted. Mirror the sidebar brand component exactly.

---

### Feed Post (1080 x 1080)

**Layout:**
- Dark `#060708` background filling canvas
- Ambient mesh blobs top-right and bottom-left (as described above)
- Brand mark top-left, 48px from edges
- Central glass card: 760px wide, 520px tall, centered vertically with slight upward offset (center-Y at 520px, not 540px)
- A real cropped screenshot of the Approval Queue card inside the glass panel
- Headline below the card: 52px Inter SemiBold, max 2 lines
- Subhead below: 28px Inter Regular, muted

**Headline options:**

Option A (tension): "Your company forgets. Contradicts itself. Acts on stale rules. Company Brain fixes that."

Option B (product-forward): "Your Slack, Notion, and GitHub — unified into one living knowledge graph that catches its own mistakes."

Option C (intrigue): "We shipped a system that quarantines itself when its own policies conflict. Meet Company Brain."

**Recommended:** Option C. It leads with the unique contradiction-detection mechanic, which has no obvious competitor, and creates genuine curiosity.

---

### Story (1080 x 1920)

**Layout (portrait):**
- Same dark background and mesh blobs
- Brand mark at top, centered, 80px from top
- Glass card occupies the middle 60% of vertical space (top 400px to bottom 800px): full-width product screenshot
- Headline at 900px Y, 52px Inter SemiBold, centered, 2-line max
- CTA button at 1050px Y: `border-radius: 999px`, `#2563eb` fill, white "Try Company Brain" text, 56px tall
- Swipe-up label at bottom: "Link in bio" in muted text

Use Option C headline, shortened: "We built a system that quarantines itself. Meet Company Brain."

---

### Caption (Feed)

```
Your ops team doesn't have a knowledge problem. They have a contradiction problem.

Slack says one thing. Notion says another. A PR lands that quietly invalidates both. Nobody notices until something breaks.

Company Brain ingests your Slack, Notion, and GitHub into a living knowledge graph — and when a merged PR contradicts an active procedure, it quarantines itself and routes the conflict to a human for review. No silent drift. No stale automation.

Built for ops, finance, and engineering teams that move fast but need an audit trail.

Available today as a web app and installable PWA.

companybrain.ai
```

**Hashtag set (tight, 12 tags):**
`#knowledgemanagement #aiops #enterpriseai #productlaunch #buildinpublic #operationstech #aiagents #automationtools #startuplife #saasproduct #techstartup #knowyourops`

---

### Carousel Concept: "The Contradiction Handshake" (5 slides)

A 5-slide carousel explaining the PR → conflict → quarantine → human review → resolution flow. Each slide: dark background, single glass card, minimal copy, product screenshot or diagram.

**Slide 1 (Hook):**
Headline: "What happens when your AI reads a contradictory policy?"
Visual: Split screen — left panel shows old Slack message ("Refunds under $100 auto-approved"), right panel shows a new GitHub PR diff removing the $100 limit. A red `AlertOctagon` icon between them.

**Slide 2 (The Problem):**
Headline: "Most AI agents just... keep running."
Visual: A simple flow diagram — `Old Rule → Agent Acts → Wrong outcome`. Minimal, white lines on dark background. No product chrome.
Subhead: "They inherit contradictions silently. The damage compounds."

**Slide 3 (The Mechanic):**
Headline: "Company Brain quarantines the conflict."
Visual: Cropped screenshot of the Reconciliation page showing a "critical" severity badge on a quarantined skill. The skill name, PR reference, and locked-at timestamp visible.
Subhead: "When a merged PR contradicts an active operating procedure, the affected skill is blocked until a human resolves it."

**Slide 4 (Resolution):**
Headline: "You decide. The system learns."
Visual: Cropped Approval Queue card — the "Dismiss" and "Accept synthesis" buttons foregrounded. Amber badge reading "Medium" visible top-right.
Subhead: "Dismiss the false positive, or accept the new synthesis. Either way, your decision recalibrates the critic."

**Slide 5 (CTA):**
Headline: "The only AI ops platform that catches its own contradictions."
Visual: The brand mark centered, large (Brain icon 80px), "Company Brain" at 32px. Below it: "Try free · companybrain.ai"
No screenshot — clean brand close.

---

### Recommended Single Best Concept

**Carousel "The Contradiction Handshake"** using Slides 1 → 3 → 5 as a compressed 3-slide version for maximum share rate.

Lead caption (for the carousel):

```
Most AI ops tools keep running even when their rules contradict each other.

We built one that stops itself.

Company Brain detects when a merged PR conflicts with an active operating procedure — quarantines the affected skill — and routes the contradiction to a human before anything goes wrong.

This is the Contradiction Handshake. Swipe to see how it works.

Available now: companybrain.ai
```

Hashtags: `#aiops #knowledgemanagement #enterpriseai #buildinpublic #productlaunch #aiagents #saasproduct #automationtools`

---

## Summary Tables

### Top Design Fixes Before Launch

| Priority | Issue | File | Effort |
|---|---|---|---|
| P0.1 | Mobile sheet: no close button, may overflow on 360px | `Header.tsx` | 30 min |
| P0.2 | `window.prompt()` breaks iOS PWA — replace with AlertDialog | `reconciliation/page.tsx:89` | 1–2 hrs |
| P0.3 | No PWA manifest or service worker — app cannot be installed | `public/`, `layout.tsx` | 2–3 hrs |
| P0.4 | "Demo Mode" label hidden on mobile | `Header.tsx` | 15 min |
| P1.1 | Reconciliation buttons 30px tall — below 44px touch target | `reconciliation/page.tsx` | 10 min |
| P1.2 | Audit stepper no scroll affordance on mobile | `audit/page.tsx` | 30 min |
| P1.3 | Sidebar says "loops running" during onboarding | `Sidebar.tsx` | 20 min |
| P2.2 | Hub connector toggles are decorative (no `onCheckedChange`) | `hub/page.tsx` | depends on API |

### Instagram Assets Summary

| Format | Dimensions | Concept |
|---|---|---|
| Feed single | 1080 × 1080 | Dark glass card + Approval Queue screenshot + Option C headline |
| Story | 1080 × 1920 | Same palette, portrait layout, CTA button |
| Carousel (full) | 1080 × 1080 × 5 slides | "Contradiction Handshake" walk-through |
| Carousel (compact) | 1080 × 1080 × 3 slides | Slides 1, 3, 5 only |

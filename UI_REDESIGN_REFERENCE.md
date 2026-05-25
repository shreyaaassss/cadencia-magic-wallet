# Cadencia UI Redesign Reference

> Complete data reference for switching from the current dark-themed UI to the Airtable-inspired editorial design system defined in `design.md`.

---

## 1. DEPLOYMENT & INFRASTRUCTURE

### Git Repository
- **Remote:** `https://github.com/shreyaaassss/cadencia-magic-wallet.git`
- **Branch:** `main`

### AWS EC2 Instance
- **IP Address:** `13.232.223.160` (from CORS_ALLOWED_ORIGINS in .env.production)
- **Region:** `ap-south-1` (Mumbai)
- **DNS:** `cadencia-magic-wallet.duckdns.org` (DuckDNS dynamic DNS)
- **AWS Account ID:** `315326805553`

### CI/CD Workflows (GitHub Actions)
| File | Trigger | What it does |
|------|---------|--------------|
| `.github/workflows/deploy.yml` | Push to main / manual | SSH into EC2, pull code, build Docker images locally, restart docker-compose |
| `.github/workflows/ci.yml` | Push to main / PR | Backend linting + tests, Frontend build check |
| `.github/workflows/cd.yml` | Tag `v*.*.*` | Build & push Docker images to GHCR |
| `backend/.github/workflows/ci.yml` | Push to main/develop | Full CI pipeline, ECR push, ECS Fargate deploy |
| `backend/.github/workflows/rollback.yml` | Manual | Emergency ECS rollback |

### Docker Stack (Production)
- **Reverse Proxy:** Caddy 2 (auto TLS, `cadencia-magic-wallet.duckdns.org`)
- **Frontend:** Next.js 16 standalone (port 3000)
- **Backend:** FastAPI + Uvicorn (port 8000)
- **Cache:** Redis 7 (Alpine)
- **Database:** RDS PostgreSQL 16 + pgvector (Multi-AZ)

---

## 2. CURRENT DESIGN SYSTEM (TO BE REPLACED)

### Theme: Dark-first, warm cream accent
- **Background:** `#111111` (near-black)
- **Foreground:** `#eeeeee` (off-white)
- **Card:** `#191919`
- **Primary:** `#ffe0c2` (warm cream/beige) with dark foreground `#081a1b`
- **Secondary:** `#393028` with foreground `#ffe0c2`
- **Muted:** `#222222` with foreground `#b4b4b4`
- **Accent:** `#2a2a2a`
- **Border:** `#201e18`
- **Input:** `#484848`
- **Ring:** `#ffe0c2`
- **Destructive:** `#e54d2e`
- **Sidebar:** `#18181b` with foreground `#f4f4f5`

### Current Fonts
- **Display:** Cormorant Garamond (serif, 300-700)
- **Body/UI:** DM Sans (sans-serif, 300-600)
- **Code:** JetBrains Mono (300-400)
- **System font:** Inter (loaded via next/font/google in layout.tsx)

### Current Border Radius
- `--radius: 0.5rem` (8px)
- `lg`: 8px, `md`: 6px, `sm`: 4px

### Current Elevation
- Heavy use of `color-mix()` for translucent backgrounds
- Noise overlay (`noise-overlay` SVG pattern at 40% opacity)
- Spotlight animation effect
- Spline 3D scene in hero
- Rotating ring/orbit animations
- Glow effects (`radial-gradient` blurs)

---

## 3. NEW DESIGN SYSTEM (FROM design.md)

### Theme: Light editorial, white canvas with signature surface cards

### Colors - Complete Mapping

#### Brand & Surface
| Token | Hex | Purpose |
|-------|-----|---------|
| `primary` | `#181d26` | Near-black. Primary CTA bg, h1/h2 type, dark surface |
| `primary-active` | `#0d1218` | Press state on primary buttons |
| `canvas` | `#ffffff` | Default page surface (background) |
| `surface-soft` | `#f8fafc` | Tabbed feature cards, featured pricing tier |
| `surface-strong` | `#e0e2e6` | Light gray CTA banner near footer |
| `surface-dark` | `#181d26` | Dark navy CTA cards mid-page |
| `surface-dark-elevated` | `#1d1f25` | Articles hero base |
| `hairline` | `#dddddd` | 1px borders for inputs, dividers, secondary buttons |

#### Text
| Token | Hex | Purpose |
|-------|-----|---------|
| `ink` | `#181d26` | Strongest text (h1/h2), same as primary |
| `body` | `#333840` | Running text |
| `muted` | `#41454d` | Footer links, breadcrumbs, captions |
| `border-strong` | `#9297a0` | Disabled secondary button outline |
| `on-primary` | `#ffffff` | Text on primary/dark surfaces |

#### Signature Card Surfaces
| Token | Hex | Purpose |
|-------|-----|---------|
| `signature-coral` | `#aa2d00` | Full-bleed dark coral signature card |
| `signature-forest` | `#0a2e0e` | Deep green signature card |
| `signature-cream` | `#f5e9d4` | Cream callout band |
| `signature-peach` | `#fcab79` | Demo-card surface |
| `signature-mint` | `#a8d8c4` | Demo-card surface |
| `signature-yellow` | `#f4d35e` | Demo-card surface |
| `signature-mustard` | `#d9a441` | Demo-card surface |

#### Semantic
| Token | Hex | Purpose |
|-------|-----|---------|
| `link` | `#1b61c9` | Inline links (NOT primary button) |
| `link-active` | `#1a3866` | Pressed link state |
| `info` | `#254fad` | Info badges |
| `info-border` | `#458fff` | Focused input outline |
| `success` | `#006400` | Confirmation states |
| `success-border` | `#39bf45` | Success borders |

### Typography

#### Font Families
- **Primary:** Haas Grotesk / Haas Groot Disp (licensed). **Substitute:** Inter Display (variable) - adjust line-height down ~5%
- **Pricing sub-system:** Inter Display at mid-weights (475/575)
- **Fallback:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif`

#### Type Scale
| Token | Size | Weight | Line Height | Use |
|-------|------|--------|-------------|-----|
| `display-xl` | 48px | 500 | 1.1 | Articles h2 |
| `display-lg` | 40px | 400 | 1.2 | Homepage h1 hero |
| `display-md` | 32px | 400 | 1.2 | Feature-section h2 |
| `title-lg` | 24px | 400 | 1.35 | Section titles |
| `title-md` | 20px | 400 | 1.5 | Sub-section titles |
| `title-sm` | 18px | 500 | 1.4 | Article-card titles |
| `label-md` | 16px | 500 | 1.4 | Demo-card titles |
| `button` | 16px | 500 | 1.4 | CTA button labels |
| `body-md` | 14px | 400 | 1.25 | Body copy, footer, nav |
| `caption` | 14px | 500 | 1.35 | Captions, meta text |
| `legal` | 13.12px | 600 | 1.2 | Cookie/legal buttons |
| `pricing-display` | 44.8px | 475 | 1.1 | Pricing h1 |
| `pricing-section` | 28px | 475 | 1.2 | Pricing section heads |
| `pricing-card-title` | 20px | 475 | 1.3 | Pricing tier plan name |

**Key principle:** Weight 400 for display. NEVER bold display headings. Emphasis via size + color, not weight.

### Border Radius
| Token | Value | Use |
|-------|-------|-----|
| `rounded-xs` | 2px | Legal/cookie buttons |
| `rounded-sm` | 6px | Text inputs, small buttons |
| `rounded-md` | 10px | Content cards, article cards |
| `rounded-lg` | 12px | Primary CTA, signature cards |
| `rounded-pill` | 9999px | Pricing buttons only |
| `rounded-full` | 50% | Circular icon buttons, avatars |

### Spacing
| Token | Value |
|-------|-------|
| `xxs` | 4px |
| `xs` | 8px |
| `sm` | 12px |
| `md` | 16px |
| `lg` | 24px |
| `xl` | 32px |
| `xxl` | 48px |
| `section` | 96px |

### Elevation Philosophy
- **Color-block first, shadow second**
- Flat: No shadow/border (body sections, nav, footer)
- Soft hairline: 1px `#dddddd` border (inputs, secondary buttons)
- Button rest: Soft drop with subtle blue-tinted glow
- No atmospheric shadows or heavy elevation anywhere

### Key Do's & Don'ts
- **DO:** Primary CTA = near-black (`#181d26`), NOT link blue (`#1b61c9`)
- **DO:** One primary CTA per viewport
- **DO:** White canvas hero, no gradient/mesh/backdrop
- **DO:** 96px vertical rhythm between sections
- **DO:** Uneven card heights in grids
- **DON'T:** Use link blue as primary button
- **DON'T:** Add gradient to hero
- **DON'T:** Bold display type (max weight 500)
- **DON'T:** Use pill radius outside pricing
- **DON'T:** Repeat same surface in consecutive bands

---

## 4. FILE-BY-FILE CHANGE MAP

### A. Global Configuration Files

#### `frontend/src/app/globals.css` (MAJOR REWRITE)
**Current:** Dark theme CSS variables
**New:** Light editorial theme with all new tokens
```
Changes needed:
- background: #111111 → #ffffff (canvas)
- foreground: #eeeeee → #181d26 (ink)
- card: #191919 → #ffffff (canvas, cards use border differentiation)
- primary: #ffe0c2 → #181d26 (near-black)
- primary-foreground: #081a1b → #ffffff (on-primary)
- secondary: #393028 → #ffffff with hairline border
- secondary-foreground: #ffe0c2 → #181d26 (ink)
- muted: #222222 → #f8fafc (surface-soft)
- muted-foreground: #b4b4b4 → #41454d
- accent: #2a2a2a → #f8fafc (surface-soft)
- accent-foreground: #eeeeee → #181d26
- border: #201e18 → #dddddd (hairline)
- input: #484848 → #dddddd (hairline)
- ring: #ffe0c2 → #458fff (info-border)
- destructive: #e54d2e → keep (semantic)
- card-foreground: #eeeeee → #181d26
- popover: #191919 → #ffffff
- popover-foreground: #eeeeee → #181d26
- sidebar variables: all need light-theme equivalents
- radius: 0.5rem → keep (maps to 8px, close to rounded-md 10px)
- Add new signature color tokens
- Add new typography tokens
```

#### `frontend/tailwind.config.ts` (EXTEND)
**Changes needed:**
- Add signature color tokens (coral, forest, cream, peach, mint, yellow, mustard)
- Add surface tokens (surface-soft, surface-strong, surface-dark)
- Add text tokens (ink, body, on-primary)
- Update border radius scale to match design tokens
- Add spacing tokens (section: 96px, xxl: 48px, etc.)
- Remove spotlight animation
- Add Inter Display font family
- Remove darkMode config (site is light-only now)

#### `frontend/src/app/layout.tsx` (FONT CHANGE)
**Current:** Loads Inter via next/font + Google Fonts link for Cormorant Garamond, DM Sans, JetBrains Mono
**New:** Replace with Inter Display (variable) as primary. Remove Cormorant Garamond and DM Sans. Keep JetBrains Mono if needed for code.
```
- Remove Cormorant Garamond font link
- Remove DM Sans font link
- Load Inter Display (variable font with 400-600 weights)
- Update body className to use new font
- Remove dark theme Toaster
```

### B. UI Component Files (shadcn/ui primitives)

#### `frontend/src/components/ui/button.tsx` (RESTYLE)
**Current:** Warm cream primary, dark background
**New variants needed:**
- `default` (button-primary): bg-[#181d26] text-white rounded-[12px] px-6 py-4 font-medium text-base
- `secondary` (button-secondary): bg-white text-[#181d26] border border-[#dddddd] rounded-[12px]
- `outline`: Same as secondary
- `ghost`: No background, text-[#181d26]
- `link`: text-[#1b61c9] no underline
- `destructive`: Keep current
- Add `pricing-pill` variant: rounded-full, for pricing page only
- Add `legal` variant: rounded-[2px], font-semibold 13px

#### `frontend/src/components/ui/card.tsx` (RESTYLE)
**Current:** Dark card bg, border
**New:** White bg, hairline border, rounded-[10px], no shadow. Add signature card variants via className.

#### `frontend/src/components/ui/input.tsx` (RESTYLE)
**Current:** Dark bg, dark border
**New:** White bg, 1px #dddddd border, rounded-[6px], h-[44px], focus: blue ring (#458fff)

#### Other UI components to update:
- `dialog.tsx` - Light bg, dark text
- `dropdown-menu.tsx` - Light bg, hairline border
- `select.tsx` - Light bg, hairline border
- `sheet.tsx` - Light bg
- `badge.tsx` - Adjust colors
- `separator.tsx` - Use hairline color
- `skeleton.tsx` - Light loading state
- `sonner.tsx` - Light toast theme
- `sidebar.tsx` - Complete light-theme restyle

### C. Layout Components

#### `frontend/src/components/layout/AppShell.tsx` (MINOR)
**Current:** `bg-background` (dark)
**New:** `bg-background` stays (will be white via CSS var change)

#### `frontend/src/components/layout/Sidebar.tsx` (MAJOR RESTYLE)
**Current:** Dark sidebar with warm accent active state
**New:** Light sidebar matching `top-nav` spec:
- White background, hairline right border
- Dark text (#181d26) for items
- Active item: subtle bg highlight, not colored
- Enterprise header: clean, minimal
- Lucide icons stay

#### `frontend/src/components/layout/TopBar.tsx` (MAJOR RESTYLE)
**Current:** 56px dark header with health dot
**New:** 64px white bar with:
- Left: Page title in body weight
- Right: Health indicator, notifications, user avatar
- 1px bottom hairline border
- No colored elements in the bar

### D. Landing Page

#### `frontend/src/app/page.tsx` (COMPLETE REWRITE)
**Current:** Dark hero with Spline 3D robot, spinning rings, noise overlay, gradient glows
**New:** Clean white canvas hero with:
- Remove: SplineScene, Spotlight, noise-overlay, hero-bg-rings, hero-bg-glow
- Hero: white canvas, generous whitespace (96px+), headline + sub-headline + button pair
- Typography: 40px/400 (display-lg) for h1, NOT serif
- Primary CTA: near-black button ("Get started for free")
- Secondary CTA: white outline button ("Book demo")
- Section rhythm: white → signature-coral card → white → cream callout → dark CTA → light CTA → footer
- Logo strip: monochrome partner logos
- Demo-card grids with product UI fragments
- Feature-card-tabbed components
- Signature coral/forest/dark cards for brand voltage
- CTA band near footer: light gray (#e0e2e6) with primary button
- Footer: 6-column light layout

#### `frontend/src/app/landing.css` (COMPLETE REWRITE)
**Current:** 279 lines of dark-themed custom CSS with animations
**New:** Editorial system CSS:
- All color references → new design tokens
- Remove: noise-overlay, hero-bg-ring, hero-bg-glow, spotlight, landing-spin animations
- Remove: all `color-mix()` translucent dark patterns
- Remove: `font-family: 'Cormorant Garamond'` everywhere
- Add: white canvas sections, signature card surfaces
- Add: 96px section padding
- Add: editorial rhythm (alternating surface bands)
- Simplify: fewer animations, trust whitespace

### E. Auth Pages

#### `frontend/src/app/(auth)/login/page.tsx` (RESTYLE)
**Current:** Dark card on dark bg, cream accent buttons
**New:** White card on white/soft bg, near-black primary CTA, hairline borders

#### `frontend/src/app/(auth)/register/page.tsx` (RESTYLE)
**Current:** Dark multi-step form
**New:** White form on white/soft bg, clear typography hierarchy

### F. App Pages (Authenticated)

#### `frontend/src/app/dashboard/page.tsx`
- StatCard: white bg, hairline border, dark text
- DataTable: white bg, hairline row dividers
- HealthBadge: muted colors on white
- All cards: white surface, no dark card backgrounds

#### `frontend/src/app/marketplace/page.tsx`
- RFQ cards: white bg, hairline borders
- Match results: clean editorial cards

#### `frontend/src/app/negotiations/page.tsx` + `[session_id]/page.tsx`
- Timeline: white bg, clean dividers
- Price chart: clean lines on white
- Status pills: editorial colors

#### `frontend/src/app/escrow/page.tsx`
- Stepper: light bg, progress indicators using new palette
- Escrow cards: white, hairline borders

#### `frontend/src/app/treasury/page.tsx`
- Charts: new chart color palette
- Pool cards: white editorial style

#### `frontend/src/app/compliance/page.tsx`
- Audit logs: white table with hairline dividers
- Tabs: clean editorial navigation

#### `frontend/src/app/settings/page.tsx` + `wallet/page.tsx`
- Forms: white bg, 6px radius inputs, 44px height
- Cards: white with hairline borders

#### `frontend/src/app/admin/page.tsx`
- Admin tables: white bg, clean data display
- Monitoring: editorial card style

### G. Shared Components (~50 files in `components/shared/`)

All need color/theme updates. Key ones:
| Component | Change |
|-----------|--------|
| `StatCard.tsx` | White bg, dark text, hairline border |
| `DataTable.tsx` | White bg, hairline row dividers |
| `StatusBadge.tsx` | Softer semantic colors on white |
| `SessionStatusPill.tsx` | New color palette |
| `NegotiationTimeline.tsx` | White bg, clean timeline dots |
| `PriceConvergenceChart.tsx` | Chart on white, new line colors |
| `EscrowStepper.tsx` | Light stepper with editorial colors |
| `SectionHeader.tsx` | Dark ink text, body-weight |
| `EmptyState.tsx` | Light empty state illustration |
| `HealthBadge.tsx` | Muted on white |
| `KycStatusBanner.tsx` | Light info/warning colors |
| `FilterChips.tsx` | Soft background chips |
| `ConfirmDialog.tsx` | White dialog bg |
| `ApiKeyModal.tsx` | White modal, clean inputs |

---

## 5. IMPLEMENTATION ORDER (RECOMMENDED)

### Phase 1: Foundation (CSS Variables + Tailwind Config)
1. `globals.css` - Replace all CSS variables with new design tokens
2. `tailwind.config.ts` - Update/extend color palette, radius, spacing
3. `layout.tsx` - Switch fonts from Cormorant Garamond → Inter Display

### Phase 2: Primitives (shadcn/ui components)
4. `button.tsx` - New variants matching design system
5. `input.tsx` - Light input style
6. `card.tsx` - Light card style
7. Other UI components (dialog, dropdown, select, sheet, badge, separator, sidebar)

### Phase 3: Layout Shell
8. `Sidebar.tsx` - Light sidebar
9. `TopBar.tsx` - Light top bar (64px)
10. `AppShell.tsx` - Verify composition

### Phase 4: Landing Page
11. `page.tsx` (landing) - Complete rewrite
12. `landing.css` - Complete rewrite

### Phase 5: Auth Pages
13. `login/page.tsx` - Light restyle
14. `register/page.tsx` - Light restyle

### Phase 6: App Pages
15. Dashboard
16. Marketplace
17. Negotiations
18. Escrow
19. Treasury
20. Compliance
21. Settings / Wallet
22. Admin

### Phase 7: Shared Components
23. Batch update all ~50 shared components (mostly color class changes)

---

## 6. DATA THAT MUST BE PRESERVED

These are NOT design elements - they are functional data/logic that must survive the redesign:

### API Endpoints (no change)
All in `src/lib/api.ts` and `src/lib/constants.ts`

### Auth Flow (no change)
Magic.link OTP + admin password login in `src/context/AuthContext.tsx`

### Wallet Integration (no change)
Algorand signing in `src/context/WalletContext.tsx`, `src/lib/magic.ts`

### React Query Queries (no change)
All `useQuery` / `useMutation` calls across pages

### Form Schemas (no change)
All zod schemas in page files

### Route Structure (no change)
```
/ → Landing
/login → Login
/register → Register
/dashboard → Dashboard
/marketplace → RFQ Management
/marketplace/catalogue → Seller Catalogue
/marketplace/profile → Seller Profile
/negotiations → Session List
/negotiations/[session_id] → Session Detail
/escrow → Escrow Management
/treasury → Treasury Dashboard
/compliance → Compliance & Audit
/settings → Enterprise Settings
/settings/wallet → Wallet Management
/admin → Admin Panel
```

### Role-Based Navigation Logic (no change)
Buyer/Seller/Admin filtering in `Sidebar.tsx`

### TypeScript Types (no change)
All interfaces in `src/types/index.ts`

### Mock Service Worker Handlers (no change)
All handlers in `src/mocks/handlers/`

---

## 7. ASSETS TO REMOVE

- Spline 3D scene (`SplineScene` component + `@splinetool/*` packages)
- Spotlight animation (`src/components/ui/spotlight.tsx`)
- Noise overlay SVG pattern
- `landing-spin` keyframe animation
- Rotating ring/orbit visualizations
- `color-mix()` translucent dark patterns
- Cormorant Garamond font (all references)
- DM Sans font (all references)
- Dark theme Toaster config

## 8. PACKAGES TO POTENTIALLY ADD

- `@fontsource/inter` or use Google Fonts CDN for Inter Display variable
- None else needed - existing Tailwind + Radix stack is perfect for this design

## 9. PACKAGES TO POTENTIALLY REMOVE

- `@splinetool/react-spline` - 3D scenes not in new design
- `@splinetool/runtime` - Same
- (Keep framer-motion for subtle transitions if desired)

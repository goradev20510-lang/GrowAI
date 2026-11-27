# ReconcileAI web: design system

**Reference:** "Autonomous Finances" (fine-n7vljkp34f.peachworlds.com), Awwwards Honorable Mention, April 2026. We borrow its design language: palette, type pairing, rhythm and the scroll-driven chrome 3D. We do not use its copy, images or `.glb` assets.

**Modes (Impeccable):** the landing page (`/`) is *Persuade* and gets full expression: 3D, a pinned scroll sequence, a preloader. The workspace (`/app/*`) is *Operate*: precision and restraint. There, 3D only appears behind the overview figure and in empty states, never behind data.

## Tokens (`src/app/globals.css`, `@theme`)

| Role | Value |
|---|---|
| Canvas | `void #000`, `ink #030304` |
| Surfaces | `s1 #0b0b0c` (cards), `s2 #141415` (overlays), `s3 #1f1f21`, `s4 #2d2d2d` |
| Text | `fg #f4f4f4`; secondary text uses white at 72%, 52% and 34% opacity |
| Hairlines | white at 10%, 16% and 28% opacity |
| Signal | `ice #bfd5dd` (matched, focus, selection), `sea #2596be` (open invoices) |
| Status | `amber #ffab00` (review), `brick #e8735f` (unmatched/error), muted white (duplicate). Every status is paired with a text label. |
| Radius | `18px` on cards, pill-shaped controls |
| Easing | `--ease-out-expo` for reveals, `--ease-out-quart` for UI state (150–250 ms) |

## Type

- **DM Sans** (display): headings, big figures. Tracking −0.035 to −0.05em. Headings end with a period ("Review queue.").
- **Inter** (body): UI text at 15px base.
- **Geist Mono**: IDs, UTRs, narrations and raw evidence only, never as decoration.
- Figures always use `.num` (tabular, lining numerals). Money uses Indian grouping (`src/lib/format.ts`).

## Rules we hold to (from Impeccable's craft floor)

- No eyebrow labels above headings, no gradient text, no grids of identical icon cards, no glassmorphism as decoration. The only blurs are the sticky nav and the command bar, where they serve a purpose.
- Section numbers only where the sequence carries meaning (the four-step "How it works").
- Text selection, caret, focus ring and scrollbars are all themed from the palette.
- Motion: one signature moment per surface (the hero ring dolly, the pinned steps). Everything respects `prefers-reduced-motion`: Lenis is off, the 3D stops rotating and the preloader is skipped.
- WebGL is lazy-loaded and client-only, with a radial-glow fallback when WebGL is unavailable. Lighting comes from in-scene Lightformers, so no HDRIs are fetched over the network.

## Libraries

`three`, `@react-three/fiber`, `@react-three/drei`, `@react-three/postprocessing` · `gsap` + `@gsap/react` (ScrollTrigger, SplitText) · `lenis` · `motion` · `@tanstack/react-query` · `cmdk` · `@radix-ui/react-tabs` · `react-dropzone` · `sonner` · `@phosphor-icons/react`.
Installed but not yet used: `@paper-design/shaders-react` and `@tanstack/react-table`. They're available if a mesh-gradient surface or a heavier data grid is needed.

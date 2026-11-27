# ReconcileAI web: design system

Plain and flat. A navy header carries the headline figures, a tab bar switches views, and tables sit directly on the page.

## Tokens (`src/app/globals.css`, `@theme`)

| Role | Value |
|---|---|
| Header | `hero #0b1d43` |
| Page | `void #0a1124`; panels `s1 #0e1830`, overlays `s2 #131f3c` |
| Text | `fg #f5f7ff`, `fg-2 #c2cce6`, `fg-3 #919ebf`, `fg-4 #7683a6` |
| Needs a person | `brick #ff5488` (review count, active tab, unmatched/error) |
| Status | `ok #25c78a` (matched, settled), `amber #ffb224` (in review), `sea #52b6ea` (open) |
| Focus, selection | `ice #8fb8ff` |
| Radius | 6–8px. Only the reviewer field and count badges are round. |

## Type

Red Hat Display for headings and large figures, Red Hat Text for UI, Red Hat Mono for IDs, UTRs and narrations. Figures use `.num`; money uses Indian grouping (`src/lib/format.ts`).

## Rules

- No 3D, scroll effects, preloaders, blur or gradients.
- Status is a text label in an outlined badge, never colour alone.
- Motion only where it explains a change (expanding a panel, switching a case).

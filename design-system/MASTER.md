# Design System Master

## Product

个人健康生活网络数据监测与分析系统 is a personal health management product. The interface must protect all profile, metric, device, family authorization, report, and audit data behind login.

## Visual System

- Direction: warm organic health interface for daily personal use, not a hospital command center.
- Surfaces: earth-toned calm backgrounds with clear form surfaces and compact cards.
- Typography: readable Chinese-first UI type; headings may use a restrained humanist serif, body text stays sans-serif.
- Radius: 16-30px for organic surfaces; controls keep stable dimensions.
- Motion: subtle transitions only; respect `prefers-reduced-motion`.

## Required UX Rules

- Login is the only pre-authenticated surface.
- Buttons must provide visible pending/success/error feedback for save, authorize, refresh, complete, and report generation actions.
- All interactive targets must be at least 44px high and expose visible `:focus-visible` outlines.
- Forms require visible labels; placeholders may only provide examples.
- Status must never rely on color alone. Pair color with text, shape, border, or an inline marker.
- Mobile layouts collapse to one column without horizontal page scroll. Data tables may scroll inside their own container.
- Charts require accessible names and readable labels.

## Audit Checklist

- Accessibility: contrast, labels, keyboard reachability, focus-visible, chart labels.
- Touch & Interaction: 44px targets, disabled states, async feedback.
- Performance: avoid layout shift, avoid heavy motion, preserve chart/container dimensions.
- Layout/Responsive: `100dvh`, mobile single column, no hidden primary actions.
- Forms & Feedback: inline messages use `role="status"` or `role="alert"` as appropriate.
- Charts & Data: legends/labels and non-color status expression.

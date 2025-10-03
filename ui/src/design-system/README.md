# Orbit Design System (Draft)

Shared theme assets powering the Orbit dashboard.

- `tokens.css` — CSS custom properties for the purple-accent palette, spacing scale, radii, and elevations (light + dark).
- `design-system.css` — utility classes (`orbit-surface`, `orbit-heading-lg`, `shadow-elev-*`, etc.) layered on top of Tailwind.
- `tokens.ts` — typed exports for the same values so React components and Storybook docs can stay in sync.

## Using in components

```tsx
import { tokens } from "../design-system";

console.log(tokens.colors.accent); // CSS variable reference
```

Apply utility classes directly in JSX:

```tsx
<div className="orbit-surface shadow-elev-2">
  <h2 className="orbit-heading-lg">Sync overview</h2>
  <p className="orbit-text-subtle">Monitor bidirectional sync activity.</p>
</div>
```

When you need raw values (e.g. inline styles or charts), use the TypeScript tokens.

```tsx
<div style={{ background: tokens.colors.accent }} />
```

## Dark mode

Toggle the `dark` class on the root element to flip the palette. All utility classes and components reference the CSS variables rather than hard-coded colors.

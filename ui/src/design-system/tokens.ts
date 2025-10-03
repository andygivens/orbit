const asHsl = (variable: string) => `hsl(var(${variable}) / 1)`;

export const colorTokens = {
  background: asHsl("--color-background"),
  surface: "var(--color-surface)",
  foreground: asHsl("--color-foreground"),
  text: "var(--color-text)",
  textSoft: "var(--color-text-soft)",
  textStrong: "var(--color-text-strong)",
  card: asHsl("--color-card"),
  cardForeground: asHsl("--color-card-foreground"),
  muted: asHsl("--color-muted"),
  mutedForeground: asHsl("--color-muted-foreground"),
  border: asHsl("--color-border"),
  hover: "var(--color-hover)",
  accent: asHsl("--color-accent"),
  accentForeground: asHsl("--color-accent-foreground"),
  accentSpectrum: {
    500: "var(--accent-500)",
    600: "var(--accent-600)",
    700: "var(--accent-700)"
  } as const,
  danger: asHsl("--color-danger"),
  dangerForeground: asHsl("--color-danger-foreground"),
  success: asHsl("--color-success"),
  successForeground: asHsl("--color-success-foreground"),
  warning: "var(--color-warning)"
} as const;

export const radiusTokens = {
  lg: "var(--radius-lg)",
  md: "var(--radius-md)",
  sm: "var(--radius-sm)"
} as const;

export const spacingTokens = {
  xs: "var(--space-xs)",
  sm: "var(--space-sm)",
  md: "var(--space-md)",
  lg: "var(--space-lg)",
  xl: "var(--space-xl)"
} as const;

export const transitionTokens = {
  fast: "var(--transition-fast)",
  default: "var(--transition-default)",
  slow: "var(--transition-slow)"
} as const;

export const shadowTokens = {
  sm: "var(--shadow-sm)",
  md: "var(--shadow-md)",
  lg: "var(--shadow-lg)",
  elevation1: "var(--shadow-1)",
  elevation2: "var(--shadow-2)",
  elevation3: "var(--shadow-3)"
} as const;

export const fontTokens = {
  sans: "var(--font-sans)",
  mono: "var(--font-mono)",
  display: "var(--type-display)",
  h1: "var(--type-h1)",
  h2: "var(--type-h2)",
  body: "var(--type-body)"
} as const;

export type ColorToken = keyof typeof colorTokens;
export type RadiusToken = keyof typeof radiusTokens;
export type SpacingToken = keyof typeof spacingTokens;
export type TransitionToken = keyof typeof transitionTokens;
export type ShadowToken = keyof typeof shadowTokens;
export type FontToken = keyof typeof fontTokens;
export type AccentShadeToken = keyof typeof colorTokens.accentSpectrum;

export const tokens = {
  colors: colorTokens,
  radii: radiusTokens,
  spacing: spacingTokens,
  transitions: transitionTokens,
  shadows: shadowTokens,
  fonts: fontTokens
} as const;

export type OrbitDesignTokens = typeof tokens;

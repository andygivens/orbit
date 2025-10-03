import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx,js,jsx}"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "monospace"]
      },
      colors: {
        background: "hsl(var(--color-background) / <alpha-value>)",
        foreground: "hsl(var(--color-foreground) / <alpha-value>)",
        muted: {
          DEFAULT: "hsl(var(--color-muted) / <alpha-value>)",
          foreground: "hsl(var(--color-muted-foreground) / <alpha-value>)"
        },
        card: {
          DEFAULT: "hsl(var(--color-card) / <alpha-value>)",
          foreground: "hsl(var(--color-card-foreground) / <alpha-value>)"
        },
        border: {
          DEFAULT: "hsl(var(--color-border) / <alpha-value>)",
          subtle: "hsl(var(--color-border) / 0.16)",
          strong: "hsl(var(--color-border) / 0.32)"
        },
        divider: "hsl(var(--color-border) / 0.12)",
        accent: {
          DEFAULT: "hsl(var(--color-accent) / <alpha-value>)",
          foreground: "hsl(var(--color-accent-foreground) / <alpha-value>)"
        },
        danger: {
          DEFAULT: "hsl(var(--color-danger) / <alpha-value>)",
          foreground: "hsl(var(--color-danger-foreground) / <alpha-value>)"
        },
        success: {
          DEFAULT: "hsl(var(--color-success) / <alpha-value>)",
          foreground: "hsl(var(--color-success-foreground) / <alpha-value>)"
        }
      },
      boxShadow: {
        sm: "0 1px 2px 0 hsl(0 0% 0% / 0.05)",
        md: "0 8px 20px hsl(0 0% 0% / 0.08)",
        lg: "0 20px 40px hsl(0 0% 0% / 0.12)"
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)"
      }
    }
  },
  plugins: []
};

export default config;

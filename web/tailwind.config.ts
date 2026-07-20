import type { Config } from "tailwindcss";

// Palette is keyed `brand` / `volt` (not literal colour names) so a future
// visual refresh never requires touching markup — mirrors the rebrand-proof
// convention used elsewhere in the ecosystem.
//
// Values are the canonical BattINFO brand pack (see ../brand/tokens.css, the
// single source of truth). The ramp is anchored on the brand tokens:
//   brand-500 = Signal Teal 500 #12A394 (fills / large display only)
//   brand-600 = Signal Teal 700 #0C7A6E (AA-safe links, buttons, teal text)
// When the brand changes, update brand/tokens.css and mirror it here.
// Neutral surfaces and text are CSS variables (RGB channels) so a single .dark
// class on <html> flips the whole UI. Brand/volt/semantic hues stay fixed.
const v = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Primary — BattINFO Signal Teal. 600 is the AA-safe text/UI shade.
        brand: {
          50: "#e4f4f1",
          100: "#c9ece6",
          200: "#9cdcd3",
          300: "#5fc6b8",
          400: "#21ad9d",
          500: "#12a394",
          600: "#0c7a6e",
          700: "#0a6358",
          800: "#084e46",
          900: "#063a34",
          950: "#042722",
        },
        // Accent — "volt": on-brand semantic success green (validation states),
        // anchored on Success #178050 / tint #E4F4EC from the brand pack.
        volt: {
          50: "#e4f4ec",
          100: "#c7e9d6",
          200: "#97d6b4",
          300: "#5bbd8b",
          400: "#2c9e66",
          500: "#178050",
          600: "#136b43",
          700: "#105737",
          800: "#0c4329",
          900: "#08301e",
        },
        ink: {
          DEFAULT: v("--c-ink"), // primary text, headers
          muted: v("--c-ink-muted"), // secondary text, captions
          faint: v("--c-ink-faint"), // tertiary labels / eyebrows
          deep: "#0a1b2c", // fixed dark surface (inverted accents)
        },
        // Semantic states — hue fixed, tint flips for dark mode.
        error: { DEFAULT: "#c8372d", tint: v("--c-error-tint") },
        warning: { DEFAULT: "#946007", tint: v("--c-warning-tint") },
        info: { DEFAULT: "#2563b8", tint: v("--c-info-tint") },
        // Neutrals & surfaces — flip with the theme.
        paper: v("--c-paper"), // page background
        surface: v("--c-surface"), // cards
        border: v("--c-border"), // hairlines
        tint: v("--c-tint"), // teal wash, tags
        // Code surfaces — light in light mode, dark in dark mode.
        code: { bg: v("--c-code-bg"), fg: v("--c-code-fg") },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      maxWidth: {
        prose: "72ch",
      },
    },
  },
  plugins: [],
};

export default config;

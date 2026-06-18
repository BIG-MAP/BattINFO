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
const config: Config = {
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
          DEFAULT: "#102a43", // Ink — primary text, headers
          muted: "#5a6570", // Muted — secondary text, captions
          faint: "#8a877e", // tertiary labels / eyebrows
        },
        // Brand neutrals & surfaces (from brand/tokens.css).
        paper: "#f3f2ee", // page background
        surface: "#ffffff", // cards
        border: "#e7e5df", // hairlines
        tint: "#e4f4f1", // teal wash, tags
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

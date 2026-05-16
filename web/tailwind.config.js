/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        // Primary: deep forest green. Rooted, alive, hopeful.
        forest: {
          50: "#EEF6EF",
          100: "#D5EAD8",
          200: "#ACD2B0",
          300: "#7AB182",
          400: "#4A8E55",
          500: "#2F6A39",
          600: "#1F4A2C",
          700: "#173B22",
          800: "#133018",
          900: "#0C1F0F",
        },
        // Accent: warm marigold. Used for CTAs, the Sprout bud, the sun.
        marigold: {
          50: "#FEF6E0",
          100: "#FCEAB4",
          200: "#F8D374",
          300: "#F2C04A",
          400: "#ECB13B",
          500: "#D89C24",
          600: "#B07E15",
          700: "#83610F",
        },
        // Backgrounds + surfaces: warm cream (a touch more yellow than before).
        cream: {
          50: "#FDFBF2",
          100: "#FAF6E8",
          200: "#F2EBD4",
          300: "#E8DCBC",
          400: "#D5C490",
        },
        // Text + borders: warm slate (unchanged; works with green).
        ink: {
          50: "#F5F4F2",
          100: "#E6E4DF",
          200: "#C7C3BA",
          300: "#9A958B",
          400: "#6E6A62",
          500: "#4A4742",
          600: "#332F2B",
          700: "#22201D",
          800: "#16140F",
          900: "#0C0A07",
        },
      },
      fontFamily: {
        sans: [
          '"Inter"',
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
        display: [
          '"Fraunces"',
          "ui-serif",
          "Georgia",
          "Cambria",
          "Times New Roman",
          "serif",
        ],
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
        "4xl": "2rem",
      },
      boxShadow: {
        soft: "0 1px 2px rgba(12, 10, 7, 0.04), 0 4px 12px rgba(12, 10, 7, 0.04)",
        lift: "0 4px 8px rgba(12, 10, 7, 0.06), 0 12px 24px rgba(12, 10, 7, 0.08)",
        glow: "0 0 0 4px rgba(31, 74, 44, 0.12)",
      },
      animation: {
        "fade-up": "fadeUp 360ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fadeIn 240ms ease-out both",
        "pulse-dot": "pulseDot 1.4s ease-in-out infinite",
        "horizon-rise": "horizonRise 900ms cubic-bezier(0.22, 1, 0.36, 1) both",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        pulseDot: {
          "0%, 80%, 100%": { opacity: "0.3", transform: "scale(0.85)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
        horizonRise: {
          "0%": { opacity: "0", transform: "translateY(12px) scale(0.96)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
    },
  },
  plugins: [],
};

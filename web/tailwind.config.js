/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        // Primary: deep forest-teal. Grounded, dignified, hopeful.
        teal: {
          50: "#EDF7F4",
          100: "#D2EBE3",
          200: "#A5D6C7",
          300: "#6FBBA4",
          400: "#3F9C82",
          500: "#1F7F66",
          600: "#0D5C4F",
          700: "#0A4A40",
          800: "#083B33",
          900: "#062E29",
        },
        // Accent: warm coral. Used sparingly for CTAs + accents.
        coral: {
          50: "#FDF1EC",
          100: "#FADCD1",
          200: "#F4B6A1",
          300: "#EC8E70",
          400: "#E08566",
          500: "#D26A47",
          600: "#B4502F",
          700: "#8E3D24",
        },
        // Backgrounds + surfaces: warm cream, not cool gray.
        cream: {
          50: "#FDFBF7",
          100: "#FAF7F2",
          200: "#F2EDE4",
          300: "#E8E0D2",
          400: "#D5C8B2",
        },
        // Text + borders: warm slate (not blue-gray).
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
        glow: "0 0 0 4px rgba(13, 92, 79, 0.12)",
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

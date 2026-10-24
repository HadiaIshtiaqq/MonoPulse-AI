import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-inter)", "ui-sans-serif", "sans-serif"],
      },
      colors: {
        ink: "#0E1022",
        brand: {
          DEFAULT: "#5B47FB",
          dark: "#4532E0",
          soft: "#EFEDFF",
          50: "#F6F5FF",
          100: "#EFEDFF",
          200: "#DCD7FF",
          300: "#BDB3FE",
          500: "#5B47FB",
          600: "#4532E0",
          700: "#3826B8",
        },
        pop: "#FF5C8A",
      },
      boxShadow: {
        card: "0 1px 2px rgba(14,16,34,.04), 0 1px 3px rgba(14,16,34,.06)",
        lift: "0 8px 24px -8px rgba(14,16,34,.18)",
        pop: "0 24px 48px -12px rgba(14,16,34,.28)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #5B47FB 0%, #9B3DF5 55%, #FF5C8A 100%)",
      },
    },
  },
  plugins: [],
};

export default config;

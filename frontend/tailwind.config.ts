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
        glow: "0 10px 30px -8px rgba(91,71,251,.55)",
        "glow-lg": "0 18px 50px -12px rgba(91,71,251,.6)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #5B47FB 0%, #9B3DF5 55%, #FF5C8A 100%)",
        "brand-gradient-wide": "linear-gradient(110deg, #5B47FB 0%, #9B3DF5 30%, #FF5C8A 50%, #9B3DF5 70%, #5B47FB 100%)",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(.2,.8,.2,1.05)",
        out: "cubic-bezier(.16,1,.3,1)",
      },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(14px)" }, to: { opacity: "1", transform: "none" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "scale-in": { from: { opacity: "0", transform: "translateY(10px) scale(.97)" }, to: { opacity: "1", transform: "none" } },
        "slide-down": { from: { opacity: "0", transform: "translateY(-8px)" }, to: { opacity: "1", transform: "none" } },
        "gradient-pan": { "0%": { backgroundPosition: "0% 50%" }, "100%": { backgroundPosition: "200% 50%" } },
        float: {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "50%": { transform: "translate3d(18px,-22px,0) scale(1.06)" },
        },
        "float-slow": {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "50%": { transform: "translate3d(-24px,16px,0) scale(1.08)" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pop-in": { "0%": { transform: "scale(.4)", opacity: "0" }, "70%": { transform: "scale(1.15)", opacity: "1" }, "100%": { transform: "scale(1)" } },
        stripes: { from: { backgroundPosition: "0 0" }, to: { backgroundPosition: "28px 0" } },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(91,71,251,.45)" },
          "100%": { boxShadow: "0 0 0 12px rgba(91,71,251,0)" },
        },
      },
      animation: {
        "fade-up": "fade-up .6s cubic-bezier(.16,1,.3,1) backwards",
        "fade-in": "fade-in .4s ease-out backwards",
        "scale-in": "scale-in .45s cubic-bezier(.16,1,.3,1) backwards",
        "slide-down": "slide-down .35s cubic-bezier(.16,1,.3,1) backwards",
        "gradient-pan": "gradient-pan 6s linear infinite",
        float: "float 14s ease-in-out infinite",
        "float-slow": "float-slow 18s ease-in-out infinite",
        "pop-in": "pop-in .45s cubic-bezier(.2,.8,.2,1.05) backwards",
        stripes: "stripes .8s linear infinite",
        "pulse-ring": "pulse-ring 1.4s cubic-bezier(.2,.8,.2,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;

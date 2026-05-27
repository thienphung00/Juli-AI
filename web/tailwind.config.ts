import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
      },
      colors: {
        primary: {
          DEFAULT: "#ff006e",
          50: "#fff0f6",
          100: "#ffe0ee",
          200: "#ffb3d3",
          300: "#ff80b5",
          400: "#ff4d94",
          500: "#ff006e",
          600: "#e6005f",
          700: "#cc0054",
          800: "#99003f",
          900: "#66002a",
        },
        brand: {
          pink: "#FF1493",
          "pink-light": "#FF85C2",
          "pink-dark": "#E61282",
          gradient: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)",
        },
        surface: {
          DEFAULT: "#0a0a0a",
          card: "#141414",
          elevated: "#1a1a1a",
          muted: "#222222",
          border: "#2a2a2a",
        },
        ink: {
          DEFAULT: "#fafafa",
          muted: "#a1a1aa",
          subtle: "#71717a",
        },
      },
      borderRadius: {
        "2xl": "16px",
        "3xl": "24px",
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(8px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};

export default config;

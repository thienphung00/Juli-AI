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
          DEFAULT: "#F86BA5",
          50: "#FEF5F6",
          100: "#FDE8EC",
          200: "#F9C4D4",
          300: "#FBA0BC",
          400: "#F98BA9",
          500: "#F86BA5",
          600: "#E85A94",
          700: "#D44983",
          800: "#B0386A",
          900: "#8C2D54",
        },
        brand: {
          pink: "#F86BA5",
          "pink-background": "#FEF5F6",
          "pink-light": "#FAA5C4",
          "pink-dark": "#E85A94",
          gradient: "linear-gradient(135deg, #F86BA5 0%, #FAA5C4 100%)",
        },
        success: "#16A34A",
        destructive: "#E5484D",
        warning: "#F59E0B",
        info: "#2563EB",
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

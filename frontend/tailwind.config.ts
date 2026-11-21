import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ok: { DEFAULT: "#16a34a", soft: "#dcfce7", text: "#15803d" },
        warn: { DEFAULT: "#eab308", soft: "#fef9c3", text: "#a16207" },
        bad: { DEFAULT: "#dc2626", soft: "#fee2e2", text: "#b91c1c" },
        accent: { DEFAULT: "#2563eb", soft: "#e4edf8", text: "#1d4ed8" },
        // Bauhaus-Primärfarben für den Tagesverlauf
        bh: { blue: "#1f3f99", yellow: "#f4c20d", red: "#d1281f", black: "#161616", paper: "#f3efe6" },
      },
      fontSize: {
        "2xs": ["0.78rem", "1.1rem"], // 12.5px (vorher 11px)
        xs: ["0.84rem", "1.2rem"], // 13.5px
        sm: ["0.95rem", "1.4rem"], // 15px
        base: ["1.02rem", "1.55rem"],
        lg: ["1.18rem", "1.7rem"],
      },
    },
  },
  plugins: [],
} satisfies Config;

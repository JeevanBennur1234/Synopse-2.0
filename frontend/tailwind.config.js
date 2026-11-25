/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          900: "#0b1526",
          800: "#12213b",
          700: "#1a2f52",
        },
      },
    },
  },
  plugins: [],
};

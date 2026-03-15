/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Score badge colour scale — matches the design spec:
        //   green ≥ 0.80, yellow 0.40–0.79, red < 0.40
        score: {
          high: '#22c55e',    // green-500
          medium: '#eab308',  // yellow-500
          low: '#ef4444',     // red-500
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'monospace'],
      },
    },
  },
  plugins: [],
}

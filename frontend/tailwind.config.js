/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        'kur-bg': '#0d1117',
        'kur-bg-card': '#161b22',
        'kur-bg-hover': '#1c2129',
        'kur-border': '#30363d',
        'kur-text': '#e6edf3',
        'kur-text-muted': '#8b949e',
        'kur-accent': '#58a6ff',
        'kur-green': '#3fb950',
        'kur-red': '#f85149',
        'kur-yellow': '#d29922',
        'kur-purple': '#bc8cff',
        'kur-orange': '#f0883e',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}

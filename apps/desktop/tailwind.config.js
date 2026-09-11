/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'bg-base': '#0a0a0a',
        'bg-elevated': '#141414',
        'bg-hover': '#1c1c1c',
        'border-subtle': '#1f1f1f',
        'border-strong': '#2a2a2a',
        'text-primary': '#f5f5f5',
        'text-secondary': '#a0a0a0',
        'text-tertiary': '#666666',
        'accent': {
          DEFAULT: '#3b82f6',
          hover: '#2563eb',
        },
        'success': '#10b981',
        'warning': '#f59e0b',
        'danger': '#ef4444',
        'code-bg': '#1a1a1a',
      },
      fontFamily: {
        sans: ['Inter', 'Geist Sans', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Geist Mono', 'monospace'],
      },
      spacing: {
        'sidebar': '280px',
        'canvas-max': '760px',
      },
    },
  },
  plugins: [],
};

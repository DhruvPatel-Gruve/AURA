import type { Config } from 'tailwindcss'
import forms from '@tailwindcss/forms'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Accent is driven by CSS variables — runtime-swappable by admin
        accent: {
          DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
          hover:   'rgb(var(--accent-hover) / <alpha-value>)',
          fg:      'rgb(var(--accent-fg) / <alpha-value>)',
          subtle:  'rgb(var(--accent) / 0.12)',
        },
        // Neutral surface system — variables swap under `.dark`, so components
        // never need dark: variants for these
        canvas:  'rgb(var(--canvas) / <alpha-value>)',   // app background
        surface: 'rgb(var(--surface) / <alpha-value>)',  // cards, panels
        sunken:  'rgb(var(--sunken) / <alpha-value>)',   // table headers, wells
        line:    'rgb(var(--line) / <alpha-value>)',     // borders, dividers
        ink:     'rgb(var(--ink) / <alpha-value>)',      // headings, primary text
        body:    'rgb(var(--body) / <alpha-value>)',     // secondary text, labels
        faint:   'rgb(var(--faint) / <alpha-value>)',    // tertiary text, placeholders
      },
      fontFamily: {
        sans:    ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['"IBM Plex Sans"', 'Inter', 'system-ui', 'sans-serif'],
        mono:    ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        overline: ['11px', { lineHeight: '16px', letterSpacing: '0.06em' }],
      },
      boxShadow: {
        'card':    '0 1px 2px 0 rgb(16 24 40 / 0.04)',
        'card-md': '0 4px 8px -2px rgb(16 24 40 / 0.08), 0 2px 4px -2px rgb(16 24 40 / 0.04)',
      },
    },
  },
  plugins: [forms],
} satisfies Config

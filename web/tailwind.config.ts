import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Background colors
        bg: 'var(--bg)',
        bgElev1: 'var(--bg-elev1)',
        bgElev2: 'var(--bg-elev2)',
        panel: 'var(--panel)',
        panelBg: 'var(--panel-bg)',
        cardBg: 'var(--card-bg)',
        chipBg: 'var(--chip-bg)',
        inputBg: 'var(--input-bg)',
        codeBg: 'var(--code-bg)',
        
        // Text colors
        fg: 'var(--fg)',
        muted: 'var(--fg-muted)',
        codeFg: 'var(--code-fg)',
        
        // Border/line
        line: 'var(--line)',
        ring: 'var(--ring)',
        
        // Brand colors
        accent: 'var(--accent)',           // NEON GREEN #00ff88
        accentContrast: 'var(--accent-contrast)',
        link: 'var(--link)',
        onLink: 'var(--on-link)',
        
        // Status colors
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        err: 'var(--err)',
        onWarn: 'var(--on-warn)',
        onErr: 'var(--on-err)'
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)']
      }
    }
  },
  plugins: []
} satisfies Config


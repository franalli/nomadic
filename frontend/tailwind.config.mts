import type { Config } from 'tailwindcss';
import defaultTheme from 'tailwindcss/defaultTheme';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        bg: 'hsl(var(--bg))',
        'bg-soft': 'hsl(var(--bg-soft))',
        'bg-strong': 'hsl(var(--bg-strong))',
        surface: 'hsl(var(--surface))',
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        text: 'hsl(var(--text))',
        'text-soft': 'hsl(var(--text-soft))',
        'text-muted': 'hsl(var(--text-muted))',
        'text-onDark': 'hsl(var(--text-onDark))',
        charcoal: 'hsl(var(--charcoal))',
        sand: 'hsl(var(--sand))',
        bronze: 'hsl(var(--bronze))',
        sky: 'hsl(var(--sky))',
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
      },
      borderRadius: {
        lg: '0.75rem',
        md: '0.5rem',
      },
      fontFamily: {
        sans: ['Inter', ...defaultTheme.fontFamily.sans],
        body: ['Inter', ...defaultTheme.fontFamily.sans],
        heading: ['"Playfair Display"', 'ui-serif', 'Georgia', 'serif'],
        display: ['"Space Grotesk"', 'Inter', ...defaultTheme.fontFamily.sans],
      },
      fontSize: {
        display: ['3.5rem', { lineHeight: '1.05', letterSpacing: '-0.04em' }],
        h2: ['2rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        h3: ['1.375rem', { lineHeight: '1.3' }],
      },
      boxShadow: {
        soft: '0 20px 45px rgba(10, 14, 18, 0.08)',
        card: '0 15px 35px rgba(10, 14, 18, 0.08)',
      },
      maxWidth: {
        content: '1200px',
      },
      spacing: {
        18: '4.75rem',
      },
    },
  },
  plugins: [],
};

export default config;

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    screens: {
      sm: '640px',
      md: '768px',
      app: '900px',
      lg: '1024px',
      xl: '1280px',
    },
    extend: {
      colors: {
        marshmallow: '#F0F0F0',
        paper: '#FAFAFA',
        violet: {
          DEFAULT: '#5B3DFF',
          dark: '#482FE0',
          light: '#7A5CFF',
          muted: '#9A86FF',
          subtle: 'rgba(91, 61, 255, 0.08)',
          glow: 'rgba(91, 61, 255, 0.22)',
        },
        pink: {
          DEFAULT: '#FF66E0',
          dark: '#B01D8F',
          muted: '#FFB3EE',
          subtle: 'rgba(255, 102, 224, 0.16)',
          glow: 'rgba(255, 102, 224, 0.2)',
        },
        ink: {
          DEFAULT: '#1A1530',
          code: '#E8E4FF',
          dark: '#141026',
        },
        mute: '#6B6780',
        line: {
          DEFAULT: 'rgba(26, 21, 48, 0.10)',
          landing: 'rgba(26, 21, 48, 0.12)',
        },
        glass: {
          DEFAULT: 'rgba(255, 255, 255, 0.62)',
          border: 'rgba(255, 255, 255, 0.8)',
        },
      },
      fontFamily: {
        display: ['Urbanist', 'Helvetica Neue', 'Arial', 'sans-serif'],
        body: ['Hanken Grotesk', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        card: '22px',
        sheet: '24px',
        stage: '28px',
        input: '12px',
        pill: '999px',
        subcard: '14px',
        req: '16px',
      },
      backdropBlur: {
        glass: '22px',
      },
      backdropSaturate: {
        glass: '1.3',
      },
      maxWidth: {
        content: '1120px',
        landing: '1160px',
      },
      letterSpacing: {
        headline: '-0.025em',
        kpi: '-0.03em',
        logo: '-0.02em',
      },
      lineHeight: {
        headline: '1.02',
        appHeadline: '1.05',
      },
    },
  },
  plugins: [],
};

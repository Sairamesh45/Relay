/**
 * Design Tokens for Relay Frontend
 * Derived 1:1 from c:\Users\hi\Downloads\relay.html
 */

export const COLORS = {
  marshmallow: '#F0F0F0',
  paper: '#FAFAFA',
  galacticViolet: '#5B3DFF',
  bubblegumPink: '#FF66E0',
  ink: '#1A1530',
  mute: '#6B6780',
  line: 'rgba(26, 21, 48, 0.10)',
  lineLanding: 'rgba(26, 21, 48, 0.12)',
  glassBg: 'rgba(255, 255, 255, 0.62)',
  glassBorder: 'rgba(255, 255, 255, 0.8)',
  glassBorderLanding: 'rgba(255, 255, 255, 0.7)',
  codeBg: '#1A1530',
  codeText: '#E8E4FF',
  codeKeyword: '#B7A8FF',
  codeString: '#FF9BEB',
  codeComment: '#8A84A8',
} as const;

export const GRADIENTS = {
  logoDot: 'linear-gradient(135deg, #5B3DFF, #FF66E0)',
  violetBar: 'linear-gradient(to top, #5B3DFF, #9A86FF)',
  pinkBar: 'linear-gradient(to top, #FF66E0, #FFB3EE)',
  horizontalScore: 'linear-gradient(90deg, #5B3DFF, #FF66E0)',
  landingStage: `radial-gradient(60% 80% at 8% 100%, #FF66E0 0, transparent 62%),
                 radial-gradient(70% 90% at 95% 0%, #5B3DFF 0, transparent 60%),
                 linear-gradient(160deg, #EDEAFF, #F7E8F6)`,
  authArt: `radial-gradient(70% 80% at 0 100%, #FF66E0, transparent 62%),
            radial-gradient(80% 90% at 100% 0, #7A5CFF, transparent 60%),
            #5B3DFF`,
  ambientUnderlay: `radial-gradient(50% 40% at 100% 0, rgba(91, 61, 255, 0.22), transparent 70%),
                    radial-gradient(45% 40% at 0 100%, rgba(255, 102, 224, 0.2), transparent 70%)`,
} as const;

export const TYPOGRAPHY = {
  display: "'Urbanist', 'Helvetica Neue', Arial, sans-serif",
  body: "'Hanken Grotesk', 'Helvetica Neue', Arial, sans-serif",
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
  headlineLetterSpacing: '-0.025em',
  kpiLetterSpacing: '-0.03em',
  logoLetterSpacing: '-0.02em',
  headlineLineHeight: '1.02',
  appHeadlineLineHeight: '1.05',
} as const;

export const RADII = {
  card: '22px',
  sheet: '24px',
  stage: '28px',
  subcard: '14px',
  reqItem: '16px',
  input: '12px',
  button: '999px',
  pill: '999px',
  badge: '99px',
} as const;

export const LAYOUT = {
  sidebarWidth: '232px',
  maxContentWidth: '1120px',
  maxLandingWidth: '1160px',
  outerPadding: '14px',
  columnGap: '20px',
  breakpointApp: 900,
} as const;

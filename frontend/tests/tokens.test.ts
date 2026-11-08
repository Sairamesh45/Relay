import { describe, it, expect } from 'vitest';
import { COLORS, RADII, TYPOGRAPHY, LAYOUT } from '../src/tokens';

describe('Design Tokens Fidelity', () => {
  it('matches exact color palette from relay.html', () => {
    expect(COLORS.marshmallow).toBe('#F0F0F0');
    expect(COLORS.paper).toBe('#FAFAFA');
    expect(COLORS.galacticViolet).toBe('#5B3DFF');
    expect(COLORS.bubblegumPink).toBe('#FF66E0');
    expect(COLORS.ink).toBe('#1A1530');
    expect(COLORS.mute).toBe('#6B6780');
    expect(COLORS.line).toBe('rgba(26, 21, 48, 0.10)');
  });

  it('matches exact radii from relay.html', () => {
    expect(RADII.card).toBe('22px');
    expect(RADII.sheet).toBe('24px');
    expect(RADII.input).toBe('12px');
    expect(RADII.button).toBe('999px');
  });

  it('matches exact layout dimensions from relay.html', () => {
    expect(LAYOUT.sidebarWidth).toBe('232px');
    expect(LAYOUT.maxContentWidth).toBe('1120px');
    expect(LAYOUT.outerPadding).toBe('14px');
    expect(LAYOUT.breakpointApp).toBe(900);
  });

  it('defines Urbanist display font and Hanken Grotesk body font', () => {
    expect(TYPOGRAPHY.display).toContain('Urbanist');
    expect(TYPOGRAPHY.body).toContain('Hanken Grotesk');
    expect(TYPOGRAPHY.headlineLetterSpacing).toBe('-0.025em');
    expect(TYPOGRAPHY.headlineLineHeight).toBe('1.02');
  });
});

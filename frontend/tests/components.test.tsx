import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  GlassCard,
  Button,
  Pill,
  SlideDrawer,
  Sparkline,
  DonutRing,
  CodeBlock,
} from '../src/components/ui';

describe('UI Primitives', () => {
  it('renders GlassCard with glassmorphism classes', () => {
    const { container } = render(
      <GlassCard data-testid="card">
        <span>Glass Content</span>
      </GlassCard>
    );
    const card = screen.getByTestId('card');
    expect(card).toBeInTheDocument();
    expect(card.className).toContain('backdrop-blur-[22px]');
    expect(card.className).toContain('rounded-card');
  });

  it('renders Button with variants and responds to click', () => {
    const handleClick = vi.fn();
    render(
      <Button variant="dark" onClick={handleClick}>
        Click Me
      </Button>
    );
    const btn = screen.getByRole('button', { name: /click me/i });
    expect(btn).toBeInTheDocument();
    expect(btn.className).toContain('bg-ink');
    fireEvent.click(btn);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders Pill with default and warning variants', () => {
    const { rerender } = render(<Pill variant="default">Healthy</Pill>);
    expect(screen.getByText('Healthy')).toBeInTheDocument();

    rerender(<Pill variant="warning">Cooling down</Pill>);
    expect(screen.getByText('Cooling down')).toBeInTheDocument();
  });

  it('renders SlideDrawer when open and triggers onClose on escape', () => {
    const handleClose = vi.fn();
    render(
      <SlideDrawer isOpen={true} onClose={handleClose} title="Connect Provider">
        <p>Drawer Body</p>
      </SlideDrawer>
    );
    expect(screen.getByText('Connect Provider')).toBeInTheDocument();
    expect(screen.getByText('Drawer Body')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('renders Sparkline SVG with polyline points', () => {
    const { container } = render(<Sparkline data={[1, 5, 2, 8, 3]} />);
    const polyline = container.querySelector('polyline');
    expect(polyline).toBeInTheDocument();
    expect(polyline?.getAttribute('stroke')).toBe('#5B3DFF');
  });

  it('renders DonutRing with percentage text', () => {
    render(<DonutRing percent={42} />);
    expect(screen.getByText('42%')).toBeInTheDocument();
  });

  it('renders CodeBlock with syntax styled text', () => {
    render(
      <CodeBlock>
        <span className="token-k">from</span> openai
      </CodeBlock>
    );
    expect(screen.getByText('from')).toBeInTheDocument();
    expect(screen.getByText(/openai/)).toBeInTheDocument();
  });
});

/**
 * The shared modal hook (plan item 8.4) — and the two defects the phase-8
 * audit found in it.
 *
 * 1. FOCUS STEAL. The effect depended on `onClose`. Two call sites pass an
 *    inline arrow, which is a new function every render, so the effect re-ran
 *    on every re-render of the owner: focus was restored and then moved to the
 *    first focusable element. Typing in the friend-search input, or ticking the
 *    eligibility gate's checkboxes, threw focus back to the top of the dialog.
 *
 * 2. ESCAPE ON A LEGAL GATE. The eligibility gate is an 18+/jurisdiction
 *    self-declaration. Escape dismissed it, turning the declaration into a
 *    keystroke. `escapeCloses: false` makes it answerable-only.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React, { useRef, useState } from 'react';
import { modalDialogProps, useModalA11y } from './useModalA11y';

const Modal: React.FC = () => {
  const [text, setText] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  // An inline arrow — a NEW identity on every render, exactly like the real
  // call sites that pass `() => setShow(false)`.
  useModalA11y(true, () => {}, ref);
  return (
    <div ref={ref} {...modalDialogProps('t')}>
      <h2 id="t">Title</h2>
      <button type="button">first</button>
      <input aria-label="field" value={text} onChange={(e) => setText(e.target.value)} />
    </div>
  );
};

describe('the modal hook (plan item 8.4)', () => {
  it('keeps focus in the input while the owner re-renders', () => {
    render(<Modal />);
    const input = screen.getByLabelText('field');
    input.focus();
    fireEvent.change(input, { target: { value: 'a' } });
    expect(document.activeElement).toBe(input);
  });

  it('does not close on Escape when escapeCloses is false', () => {
    const onClose = vi.fn();
    const Gate: React.FC = () => {
      const ref = useRef<HTMLDivElement>(null);
      useModalA11y(true, onClose, ref, { escapeCloses: false });
      return (
        <div ref={ref} {...modalDialogProps('g')}>
          <h2 id="g">Gate</h2>
          <button type="button">accept</button>
        </div>
      );
    };
    render(<Gate />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape by default', () => {
    const onClose = vi.fn();
    const Dialog: React.FC = () => {
      const ref = useRef<HTMLDivElement>(null);
      useModalA11y(true, onClose, ref);
      return (
        <div ref={ref} {...modalDialogProps('d')}>
          <h2 id="d">Dialog</h2>
          <button type="button">ok</button>
        </div>
      );
    };
    render(<Dialog />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

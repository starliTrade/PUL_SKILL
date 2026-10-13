/**
 * Audit 8.3 — keyboard operability for elements that cannot be a `<button>`.
 *
 * A breadcrumb (text only) became a real `<button>`. A history ROW cannot: it
 * contains block-level children, and HTML forbids a `<button>` from containing
 * them. For those the correct pattern is the ARIA one — `role="button"`,
 * `tabIndex={0}`, and Enter/Space activation — which is what this helper
 * provides, so the four call sites cannot drift apart.
 */
import type React from 'react';

export interface ClickableDivProps {
  role: 'button';
  tabIndex: 0;
  onClick: () => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
}

/**
 * The props that make a `<div>` behave like a button for keyboard users.
 *
 * `onClick` is the same handler the pointer path uses, so the two cannot
 * diverge. Space is prevented from scrolling the page, and both Enter and Space
 * activate — matching a native button.
 */
export function clickableDivProps(onActivate: () => void): ClickableDivProps {
  return {
    role: 'button',
    tabIndex: 0,
    onClick: onActivate,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        onActivate();
      }
    },
  };
}

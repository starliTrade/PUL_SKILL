/**
 * Audit 8.4 — the shared modal behaviour (role, focus trap, Escape, restore).
 *
 * The four modals were plain `<div>` overlays: no `role="dialog"`, no
 * `aria-modal`, no focus trap, and Escape did nothing. A keyboard or screen
 * reader user could tab straight out of the dialog into the page behind it, and
 * a screen reader announced the dialog's contents as ordinary page content.
 *
 * This hook is the ONE implementation, so the four cannot drift apart:
 *   - moves focus into the dialog when it opens;
 *   - keeps Tab/Shift+Tab cycling inside it (a focus trap);
 *   - closes on Escape;
 *   - restores focus to whatever had it before the dialog opened.
 *
 * The caller adds `role="dialog"`, `aria-modal="true"` and `aria-labelledby`
 * (see `modalDialogProps`) plus `tabIndex={-1}` so the container itself can
 * receive focus when it holds nothing focusable.
 */
import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

export interface ModalA11yOptions {
  /**
   * Whether Escape closes the dialog. Default true.
   *
   * Set false for a dialog the user must ANSWER rather than dismiss — the
   * eligibility gate is a self-declaration, and letting Escape skip it turns a
   * legal prompt into a keystroke.
   */
  escapeCloses?: boolean;
}

export function useModalA11y(
  isOpen: boolean,
  onClose: () => void,
  containerRef: RefObject<HTMLElement | null>,
  options: ModalA11yOptions = {}
): void {
  const { escapeCloses = true } = options;

  // `onClose` is read through a ref, NOT a dependency.
  //
  // Two of the four call sites pass an inline arrow (`() => setShow(false)`),
  // which is a NEW function on every render. With `onClose` in the dependency
  // array the effect re-ran on every re-render of the owner — restoring focus
  // to whatever had it before and then moving it to the first focusable
  // element. Typing in the friend-search input, or ticking the eligibility
  // gate's checkboxes, threw focus back to the top of the dialog.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;
    const container = containerRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusables = (): HTMLElement[] =>
      container ? Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)) : [];

    // Move focus in. The container itself is the fallback (it has tabIndex={-1}).
    const first = focusables()[0];
    (first ?? container)?.focus?.();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (!escapeCloses) return; // a gate must be answered, not dismissed
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) {
        // Nothing to cycle through: keep focus on the dialog rather than
        // letting Tab walk into the page behind it.
        event.preventDefault();
        container?.focus?.();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === firstItem || active === container)) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && active === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      previouslyFocused?.focus?.();
    };
  }, [isOpen, containerRef, escapeCloses]);
}

/** The ARIA attributes every modal container needs (audit 8.4). */
export function modalDialogProps(titleId: string) {
  return {
    role: 'dialog' as const,
    'aria-modal': true as const,
    'aria-labelledby': titleId,
    tabIndex: -1,
  };
}

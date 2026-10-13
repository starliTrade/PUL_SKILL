import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { axeViolations, describeViolations } from './a11y';

describe('axe works in this environment', () => {
  it('flags a button with no accessible name', async () => {
    const { container } = render(<button type="button" />);
    const found = await axeViolations(container);
    expect(found.length, describeViolations(found)).toBeGreaterThan(0);
    expect(found.map((v) => v.id)).toContain('button-name');
  });

  it('passes a labelled button', async () => {
    const { container } = render(<button type="button">Save</button>);
    expect(await axeViolations(container)).toEqual([]);
  });
});

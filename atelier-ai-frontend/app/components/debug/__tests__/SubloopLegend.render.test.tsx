import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';

import SubloopLegend from '../SubloopLegend';

describe('SubloopLegend', () => {
  it('renders legend entries with swatches', () => {
    render(<SubloopLegend />);

    const general = screen.getByText('Availability overview');
    const shortcut = screen.getByText('Shortcut');

    expect(general).toBeInTheDocument();
    expect(shortcut).toBeInTheDocument();

    const swatches = screen.getAllByRole('presentation', { hidden: true });
    expect(swatches).toHaveLength(2);
    expect(swatches[0]).toHaveStyle({ backgroundColor: '#2E77D0' });
    expect(swatches[1]).toHaveStyle({ backgroundColor: '#7A3EE6' });
  });
});

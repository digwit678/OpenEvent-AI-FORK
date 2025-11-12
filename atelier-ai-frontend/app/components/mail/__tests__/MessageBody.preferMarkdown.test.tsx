/// <reference types="vitest" />
// @vitest-environment jsdom

import React from 'react';
import { render, screen } from '@testing-library/react';
import MessageBody from '../MessageBody';

describe('MessageBody chooses body_markdown over render_body', () => {
  it('renders body_markdown when present', () => {
    const msg = {
      body_markdown: '### Room A — Available\n- **Available dates:** 01.02., 08.02., 15.02.',
      render_body: 'fallback plain',
    };
    render(<MessageBody msg={msg as any} />);
    expect(screen.getByText('Room A — Available')).not.toBeNull();
    expect(screen.queryByText('fallback plain')).toBeNull();
  });
});

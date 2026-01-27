/// <reference types="vitest" />
// @vitest-environment jsdom

import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import MessageBody from '../MessageBody';

describe('MessageBody fallbacks', () => {
  it('renders render_body when markdown fields are absent', () => {
    const msg = {
      render_body: 'Plain render body',
      body: 'legacy',
    };
    render(<MessageBody msg={msg as any} />);
    expect(screen.getByText('Plain render body')).toBeInTheDocument();
    expect(screen.queryByText('legacy')).toBeNull();
  });

  it('falls back to prompt when no body fields are present', () => {
    const msg = {
      prompt: 'Prompt fallback text',
    };
    render(<MessageBody msg={msg as any} />);
    expect(screen.getByText('Prompt fallback text')).toBeInTheDocument();
  });
});

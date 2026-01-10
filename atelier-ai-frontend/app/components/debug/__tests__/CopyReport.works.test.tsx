import { describe, it, expect, vi } from 'vitest';

import { copyTextWithFallback } from '../copy';

describe('copyTextWithFallback', () => {
  it('uses navigator.clipboard when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    await copyTextWithFallback('example', { navigator: { clipboard: { writeText } } as any });
    expect(writeText).toHaveBeenCalledWith('example');
  });

  it('falls back to execCommand when clipboard rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    const select = vi.fn();
    const setSelectionRange = vi.fn();
    const appendChild = vi.fn();
    const removeChild = vi.fn();
    const execCommand = vi.fn().mockReturnValue(true);

    const textarea = {
      value: '',
      setAttribute: vi.fn(),
      style: {},
      select,
      setSelectionRange,
      focus: vi.fn(),
    } as unknown as HTMLTextAreaElement;

    const documentMock = {
      createElement: vi.fn().mockReturnValue(textarea),
      body: { appendChild, removeChild },
      execCommand,
    } as unknown as Document;

    await copyTextWithFallback('fallback', {
      navigator: { clipboard: { writeText } } as any,
      document: documentMock,
    });

    expect(documentMock.createElement).toHaveBeenCalledWith('textarea');
    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});

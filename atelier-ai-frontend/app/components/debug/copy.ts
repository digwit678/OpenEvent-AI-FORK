interface CopyEnv {
  navigator?: Pick<Navigator, 'clipboard'>;
  document?: Document;
}

export async function copyTextWithFallback(text: string, env?: CopyEnv): Promise<void> {
  if (!text) {
    return;
  }
  const navSource = env?.navigator ?? (typeof navigator !== 'undefined' ? navigator : undefined);
  const docSource = env?.document ?? (typeof document !== 'undefined' ? document : undefined);

  if (navSource?.clipboard?.writeText) {
    try {
      await navSource.clipboard.writeText(text);
      return;
    } catch {
      // fall back to manual copy
    }
  }

  if (!docSource) {
    throw new Error('Clipboard not available');
  }

  const textarea = docSource.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.top = '-1000px';
  docSource.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const succeeded = docSource.execCommand ? docSource.execCommand('copy') : document.execCommand('copy');
  docSource.body.removeChild(textarea);
  if (!succeeded) {
    throw new Error('Copy command was rejected');
  }
}

'use client';

import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';

import type { TracePromptInfo } from './TraceTypes';
import type { GranularityLevel } from '../debug/utils';

interface PromptCellProps {
  prompt?: TracePromptInfo;
  granularity: GranularityLevel;
}

interface PromptToggleProps {
  label: string;
  text: string;
  defaultOpen: boolean;
}

function PromptToggle({ label, text, defaultOpen }: PromptToggleProps) {
  const [open, setOpen] = useState(defaultOpen);
  if (!text) {
    return (
      <div className="prompt-toggle prompt-toggle--empty">
        <span className="prompt-toggle__label">{label}</span>
        <span className="trace-muted">—</span>
      </div>
    );
  }
  return (
    <div className={`prompt-toggle${open ? ' prompt-toggle--open' : ''}`}>
      <button type="button" className="prompt-toggle__button" onClick={() => setOpen((prev) => !prev)}>
        <span className="prompt-toggle__label">{label}</span>
        {open ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
      {open && <pre className="prompt-toggle__content">{text}</pre>}
    </div>
  );
}

export default function PromptCell({ prompt, granularity }: PromptCellProps) {
  if (!prompt || (!prompt.instruction && !prompt.reply)) {
    return <span className="trace-muted">—</span>;
  }
  const defaultOpen = granularity === 'full';
  return (
    <div className="prompt-cell">
      {prompt.instruction ? (
        <PromptToggle label="Instruction" text={prompt.instruction} defaultOpen={defaultOpen} />
      ) : (
        <div className="prompt-toggle prompt-toggle--empty">
          <span className="prompt-toggle__label">Instruction</span>
          <span className="trace-muted">—</span>
        </div>
      )}
      {prompt.reply ? (
        <PromptToggle label="Reply" text={prompt.reply} defaultOpen={defaultOpen} />
      ) : (
        <div className="prompt-toggle prompt-toggle--empty">
          <span className="prompt-toggle__label">Reply</span>
          <span className="trace-muted">—</span>
        </div>
      )}
    </div>
  );
}

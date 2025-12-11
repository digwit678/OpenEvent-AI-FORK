import React, { useEffect, useMemo, useState } from 'react';
import { Copy } from 'lucide-react';

import type { PromptTabPayload, RawTraceEvent } from './utils';
import { copyTextWithFallback } from './copy';

type CopyState = 'idle' | 'copied' | 'error';

interface PromptPreviewProps {
  label: React.ReactNode;
  payload: PromptTabPayload;
  raw: RawTraceEvent;
}

type TabKey = 'prompt' | 'payload' | 'model' | 'raw';

const TAB_LABELS: Record<TabKey, string> = {
  prompt: 'Prompt',
  payload: 'Payload',
  model: 'Model',
  raw: 'Raw event',
};

function formatValue(value: unknown): string {
  if (value == null) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function PromptPreview({ label, payload, raw }: PromptPreviewProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('prompt');
  const [copyState, setCopyState] = useState<CopyState>('idle');

  const contentByTab = useMemo(() => {
    return {
      prompt: payload.prompt ?? '',
      payload: payload.toolPayload ?? null,
      model: payload.modelChoice ?? null,
      raw,
    } satisfies Record<TabKey, unknown>;
  }, [payload, raw]);

  const availableTabs = useMemo(() => {
    return (Object.keys(contentByTab) as TabKey[]).filter((key) => {
      const value = contentByTab[key];
      if (key === 'raw') {
        return true;
      }
      if (value == null) {
        return false;
      }
      if (typeof value === 'string') {
        return value.trim().length > 0;
      }
      if (Array.isArray(value)) {
        return value.length > 0;
      }
      if (typeof value === 'object') {
        return Object.keys(value as Record<string, unknown>).length > 0;
      }
      return true;
    });
  }, [contentByTab]);

  useEffect(() => {
    if (!availableTabs.includes(activeTab)) {
      setActiveTab(availableTabs[0] ?? 'raw');
    }
  }, [availableTabs, activeTab]);

  useEffect(() => {
    if (copyState === 'idle') {
      return;
    }
    const timer = window.setTimeout(() => setCopyState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  if (!availableTabs.length) {
    return <span className="trace-muted">—</span>;
  }

  const activeContent = formatValue(contentByTab[activeTab]);

  const handleCopy = async () => {
    if (!activeContent) {
      return;
    }
    try {
      await copyTextWithFallback(activeContent);
      setCopyState('copied');
    } catch (error) {
      console.warn('[Debug] Failed to copy prompt preview', error);
      setCopyState('error');
    }
  };

  const closeModal = () => {
    setOpen(false);
    setCopyState('idle');
  };

  return (
    <>
      <button
        type="button"
        className="prompt-preview__trigger"
        onClick={() => setOpen(true)}
        title="View prompt payload"
      >
        {label}
      </button>
      {open ? (
        <div className="prompt-modal__backdrop" onClick={closeModal} role="presentation">
          <div className="prompt-modal" role="dialog" onClick={(event) => event.stopPropagation()}>
            <header className="prompt-modal__header">
              <div>
                <h2>Prompt payload</h2>
                <p className="prompt-modal__meta">{raw.owner_step || raw.step || raw.entity || 'Trace event'}</p>
              </div>
              <button type="button" className="prompt-modal__close" onClick={closeModal} aria-label="Close prompt modal">
                ×
              </button>
            </header>

            <div className="prompt-modal__tabs" role="tablist">
              {availableTabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={tab === activeTab ? 'active' : ''}
                  onClick={() => setActiveTab(tab)}
                  role="tab"
                  aria-selected={tab === activeTab}
                >
                  {TAB_LABELS[tab]}
                </button>
              ))}
            </div>

            <div className="prompt-modal__actions">
              <button
                type="button"
                onClick={handleCopy}
                className={
                  copyState === 'copied'
                    ? 'active'
                    : copyState === 'error'
                      ? 'error'
                      : ''
                }
              >
                <Copy size={14} />
                {copyState === 'copied'
                  ? 'Copied'
                  : copyState === 'error'
                    ? 'Copy failed'
                    : 'Copy contents'}
              </button>
            </div>

            <pre className="prompt-modal__content">{activeContent || '—'}</pre>
          </div>
        </div>
      ) : null}
    </>
  );
}

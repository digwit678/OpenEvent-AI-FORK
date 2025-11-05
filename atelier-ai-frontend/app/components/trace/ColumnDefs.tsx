'use client';

import { ReactNode, useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Copy, Eye, Clock } from 'lucide-react';

import { TraceFunctionArg, TraceRowData, TraceValueItem } from './TraceTypes';
import PromptCell from './PromptCell';
import type { GranularityLevel } from '../debug/utils';

export interface TraceColumnContext {
  hilOpen: boolean;
  granularity: GranularityLevel;
  onInspect: (row: TraceRowData) => void;
  onTimeTravel: (row: TraceRowData) => void;
}

export interface TraceColumnDef {
  id: string;
  label: string;
  width: number;
  sticky?: boolean;
  align?: 'left' | 'right' | 'center';
  className?: string;
  render: (row: TraceRowData, context: TraceColumnContext) => ReactNode;
}

function renderValueItems(items: TraceValueItem[]): ReactNode {
  if (!items.length) {
    return <span className="trace-muted">—</span>;
  }
  return items.map((item, index) => {
    if (item.kind === 'chip') {
      return (
        <span key={`${item.label}-${index}`} className={`trace-chip trace-chip--${item.tone}`}>
          {item.label}
        </span>
      );
    }
    return (
      <span key={`${item.label}-${index}`} className={`trace-text${item.muted ? ' trace-text--muted' : ''}`}>
        {item.label}
      </span>
    );
  });
}

function renderIo(row: TraceRowData): ReactNode {
  if (!row.io) {
    return <span className="trace-muted">—</span>;
  }
  const direction = row.io.direction ? row.io.direction.toUpperCase() : '';
  const op = row.io.op || '';
  const result = row.io.result ? ` → ${row.io.result}` : '';
  const summary = `${direction} ${op}`.trim() + result;
  return summary ? summary : <span className="trace-muted">—</span>;
}

function renderGate(row: TraceRowData): ReactNode {
  if (!row.gate) {
    return <span className="trace-muted">—</span>;
  }
  const ratio = `${row.gate.met}/${row.gate.required}`;
  return (
    <div className="trace-gate">
      <span className="trace-chip trace-chip--gate">{ratio}</span>
      {row.gate.missing?.length ? (
        <div className="trace-gate__missing">
          {row.gate.missing.map((label) => (
            <span key={label} className="trace-chip trace-chip--missing">{label}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

type CopyState = 'idle' | 'copied' | 'error';

interface ValueModalProps {
  label: string;
  value: string;
  copyState: CopyState;
  onCopy: () => void;
  onClose: () => void;
}

function ValueModal({ label, value, copyState, onCopy, onClose }: ValueModalProps) {
  return createPortal(
    <div className="prompt-modal__backdrop" onClick={onClose} role="presentation">
      <div className="prompt-modal" onClick={(event) => event.stopPropagation()} role="dialog">
        <header className="prompt-modal__header">
          <div>
            <h2>Argument Value</h2>
            <p className="prompt-modal__meta">{label}</p>
          </div>
          <button type="button" onClick={onClose} className="prompt-modal__close" aria-label="Close">
            ×
          </button>
        </header>
        <div className="prompt-modal__actions">
          <button
            type="button"
            onClick={onCopy}
            className={copyState === 'error' ? 'error' : copyState === 'copied' ? 'active' : ''}
          >
            <Copy size={14} />
            {copyState === 'copied' ? 'Copied' : copyState === 'error' ? 'Copy failed' : 'Copy to clipboard'}
          </button>
        </div>
        <pre className="prompt-modal__content">{value}</pre>
      </div>
    </div>,
    document.body,
  );
}

interface FunctionArgValueProps {
  arg: TraceFunctionArg;
  contextLabel: string;
}

function FunctionArgValue({ arg, contextLabel }: FunctionArgValueProps) {
  const [open, setOpen] = useState(false);
  const [copyState, setCopyState] = useState<CopyState>('idle');

  useEffect(() => {
    if (copyState === 'idle') {
      return;
    }
    const timer = window.setTimeout(() => setCopyState('idle'), 1800);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(arg.fullValue);
      setCopyState('copied');
    } catch (error) {
      console.warn('Copy failed', error);
      setCopyState('error');
    }
  }, [arg.fullValue]);

  const handleClose = useCallback(() => {
    setOpen(false);
    setCopyState('idle');
  }, []);

  return (
    <>
      <button
        type="button"
        className="trace-function__arg-value"
        title={arg.fullValue}
        onClick={() => setOpen(true)}
      >
        {arg.value}
      </button>
      {open && (
        <ValueModal
          label={`${contextLabel} · ${arg.key}`}
          value={arg.fullValue}
          copyState={copyState}
          onCopy={handleCopy}
          onClose={handleClose}
        />
      )}
    </>
  );
}

function renderFunctionDetails(row: TraceRowData): ReactNode {
  const path = row.functionPath || row.functionName;
  const args = row.functionArgs || [];
  if (!path && !args.length) {
    return <span className="trace-muted">—</span>;
  }
  return (
    <div className="trace-function">
      {path ? (
        <div className="trace-function__path" title={path}>
          {path}
        </div>
      ) : null}
      {args.length ? (
        <div className="trace-function__args">
          {args.map((arg) => (
            <span key={`${arg.key}:${arg.value}`} className="trace-function__arg">
              <span className="trace-function__arg-key">{arg.key}</span>
              <span className="trace-function__arg-sep">=</span>
              <FunctionArgValue arg={arg} contextLabel={path || row.functionName} />
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export const TRACE_COLUMNS: TraceColumnDef[] = [
  {
    id: 'step',
    label: 'Step',
    width: 120,
    sticky: true,
    render: (row, context) => (
      <div className="trace-step" title={row.stepTitle}>
        <div className="trace-step__actions">
          <button
            type="button"
            className="trace-step__inspect"
            onClick={() => context.onInspect(row)}
            aria-label="View raw event"
          >
            <Eye size={14} />
          </button>
          <button
            type="button"
            className="trace-step__time-travel"
            onClick={() => context.onTimeTravel(row)}
            aria-label="View state at this event"
          >
            <Clock size={14} />
          </button>
        </div>
        <span className="trace-step__label">{row.stepLabel}</span>
      </div>
    ),
  },
  {
    id: 'entity',
    label: 'Entity',
    width: 140,
    sticky: true,
    render: (row) => (
      <span className={`trace-entity trace-entity--${row.entity}`}>{row.entity}</span>
    ),
  },
  {
    id: 'actor',
    label: 'Actor',
    width: 120,
    sticky: true,
    render: (row) => row.actor || <span className="trace-muted">—</span>,
  },
  {
    id: 'event',
    label: 'Event',
    width: 150,
    sticky: true,
    render: (row) => row.event || <span className="trace-muted">—</span>,
  },
  {
    id: 'details',
    label: 'Details (Function)',
    width: 220,
    sticky: true,
    render: (row) => renderFunctionDetails(row),
  },
  {
    id: 'value',
    label: 'Value / Output',
    width: 280,
    render: (row) => renderValueItems(row.valueItems),
  },
  {
    id: 'gate',
    label: 'Gate',
    width: 140,
    render: (row) => renderGate(row),
  },
  {
    id: 'io',
    label: 'I/O',
    width: 200,
    render: (row) => renderIo(row),
  },
  {
    id: 'wait',
    label: 'Wait',
    width: 160,
    render: (row, context) => {
      if (!row.wait) {
        return <span className="trace-muted">—</span>;
      }
      if (row.wait === 'Waiting on HIL' && !context.hilOpen) {
        return <span className="trace-muted">—</span>;
      }
      return row.wait;
    },
  },
  {
    id: 'time',
    label: 'Time',
    width: 120,
    align: 'right',
    render: (row) => row.timeLabel,
  },
  {
    id: 'prompt',
    label: 'Prompt (Agent In / Out)',
    width: 320,
    render: (row, context) => (
      <PromptCell prompt={row.prompt} granularity={context.granularity} />
    ),
  },
];

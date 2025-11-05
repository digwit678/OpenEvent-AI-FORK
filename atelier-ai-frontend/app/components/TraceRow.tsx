'use client';

import { useMemo } from 'react';
import { Eye } from 'lucide-react';
import { DisplayRow } from './debug/utils';
import PromptPreview from './debug/PromptPreview';

interface TraceRowProps {
  row: DisplayRow;
  onInspect: (row: DisplayRow) => void;
}

const ENTITY_CLASS_MAP: Record<string, string> = {
  Trigger: 'entity-pill entity-pill--trigger',
  Agent: 'entity-pill entity-pill--agent',
  'DB Action': 'entity-pill entity-pill--db',
  Condition: 'entity-pill entity-pill--condition',
  HIL: 'entity-pill entity-pill--hil',
  Detour: 'entity-pill entity-pill--detour',
  'Q&A': 'entity-pill entity-pill--qa',
  Waiting: 'entity-pill entity-pill--waiting',
  Draft: 'entity-pill entity-pill--draft',
};

export default function TraceRow({ row, onInspect }: TraceRowProps) {
  const entityClass = ENTITY_CLASS_MAP[row.entity] || 'entity-pill';
  const ioSummary = useMemo(() => {
    if (!row.io) return '';
    const direction = row.io.direction ? row.io.direction.toUpperCase() : '';
    const op = row.io.op || '';
    const result = row.io.result ? ` → ${row.io.result}` : '';
    return `${direction} ${op}`.trim() + result;
  }, [row.io]);
  const gateLabel = useMemo(() => {
    if (!row.gate) return '—';
    return `${row.gate.met}/${row.gate.required}`;
  }, [row.gate]);

  return (
    <div className="trace-row" role="row">
      <div className="trace-row__step" title={row.stepTitle}>{row.stepLabel}</div>
      <div className="trace-row__entity">
        <span className={entityClass}>{row.entity}</span>
      </div>
      <div className="trace-row__actor">{row.actor}</div>
      <div className="trace-row__event" title={row.eventLabel}>{row.eventLabel}</div>
      <div className="trace-row__details" title={row.details}>{row.details}</div>
      <div className="trace-row__captured">
        {row.capturedChips.length ? row.capturedChips.map((chip) => (
          <span key={`${row.rowId}-cap-${chip}`} className="client-chip client-chip--captured">{chip}</span>
        )) : <span className="trace-muted">—</span>}
      </div>
      <div className="trace-row__confirmed">
        {row.confirmedChips.length ? row.confirmedChips.map((chip) => (
          <span key={`${row.rowId}-conf-${chip}`} className="client-chip client-chip--confirmed">{chip}</span>
        )) : <span className="trace-muted">—</span>}
      </div>
      <div className="trace-row__gate">
        {row.gate ? (
          <div className="trace-row__gate-content">
            <span className="trace-chip-small">{gateLabel}</span>
            {row.gate.missing.length > 0 && (
              <div className="trace-row__gate-missing">
                {row.gate.missing.map((item) => (
                  <span key={`${row.rowId}-missing-${item}`} className="gate-chip-missing">{item}</span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <span className="trace-muted">—</span>
        )}
      </div>
      <div className="trace-row__io" title={ioSummary || undefined}>
        {ioSummary || <span className="trace-muted">—</span>}
      </div>
      <div className="trace-row__wait" title={row.waitState || undefined}>
        {row.waitState || <span className="trace-muted">—</span>}
      </div>
      <div className="trace-row__time">{row.timeLabel}</div>
      <div className="trace-row__prompt">
        {row.promptPreview ? <span className="trace-row__prompt-preview" title={row.promptPreview}>{row.promptPreview}</span> : <span className="trace-muted">—</span>}
        {row.promptTabs && <PromptPreview label={<Eye size={14} />} payload={row.promptTabs} raw={row.raw} />}
      </div>
      <div className="trace-row__actions">
        <button type="button" className="trace-row__inspect" onClick={() => onInspect(row)}>
          View JSON
        </button>
      </div>
    </div>
  );
}

import React from 'react';

export type GateInfo = {
  label?: string;
  result?: string;
  prereq?: string;
  inputs?: Record<string, unknown>;
};

export type EntityInfo = {
  lifecycle?: string;
  key?: string;
  value?: unknown;
  previous_value?: unknown;
};

export type DbInfo = {
  op?: string;
  mode?: string;
  duration_ms?: number;
};

export type DraftInfo = {
  footer?: {
    step?: string | null;
    next?: string | null;
    state?: string | null;
  };
};

export interface TraceEventRow {
  index: number;
  thread_id: string;
  ts: number;
  formattedTime: string;
  kind: string;
  lane: string;
  ownerStep?: string | null;
  ownerLabel?: string;
  step?: string | null;
  detail?: string | null;
  subject?: string | null;
  status?: string | null;
  summary?: string | null;
  wait_state?: string | null;
  loop?: boolean;
  detour_to_step?: number | null;
  details?: Record<string, unknown> | null;
  gate?: GateInfo | null;
  entity?: EntityInfo | null;
  db?: DbInfo | null;
  draft?: DraftInfo | null;
}

interface TraceRowProps {
  event: TraceEventRow;
  isExpanded: boolean;
  onToggle: () => void;
}

const laneClass: Record<string, string> = {
  step: 'lane-chip lane-chip--step',
  gate: 'lane-chip lane-chip--gate',
  db: 'lane-chip lane-chip--db',
  entity: 'lane-chip lane-chip--entity',
  detour: 'lane-chip lane-chip--detour',
  qa: 'lane-chip lane-chip--qa',
  draft: 'lane-chip lane-chip--draft',
};

const laneLabel: Record<string, string> = {
  step: 'Step',
  gate: 'Gate',
  db: 'DB',
  entity: 'Entity',
  detour: 'Detour',
  qa: 'Q&A',
  draft: 'Draft',
};

const statusClass: Record<string, string> = {
  captured: 'status-pill status-pill--captured',
  confirmed: 'status-pill status-pill--confirmed',
  changed: 'status-pill status-pill--changed',
  checked: 'status-pill status-pill--checked',
  pass: 'status-pill status-pill--pass',
  fail: 'status-pill status-pill--fail',
};

const statusLabel: Record<string, string> = {
  captured: 'Captured',
  confirmed: 'Confirmed',
  changed: 'Changed',
  checked: 'Checked',
  pass: 'Pass',
  fail: 'Fail',
};

function renderGateCell(gate?: GateInfo | null): string {
  if (!gate) {
    return '—';
  }
  const label = gate.label || gate.prereq || 'Gate';
  const result = gate.result || 'Result';
  const inputs = gate.inputs || {};
  const inputPreview = Object.keys(inputs).length
    ? ` (${Object.entries(inputs)
        .slice(0, 3)
        .map(([key, value]) => `${key}=${String(value)}`)
        .join(', ')})`
    : '';
  return `${label}: ${result}${inputPreview}`;
}

function renderEntityCell(entity?: EntityInfo | null): React.ReactNode {
  if (!entity || !entity.key) {
    return '—';
  }
  const lifecycle = entity.lifecycle || 'captured';
  const className = `entity-badge entity-badge--${lifecycle}`;
  const previous = entity.previous_value !== undefined && entity.previous_value !== null ? ` (prev: ${String(entity.previous_value)})` : '';
  return <span className={className}>{`${entity.key}=${String(entity.value ?? '—')}${previous}`}</span>;
}

function renderIoCell(event: TraceEventRow): string {
  if (event.db) {
    const mode = event.db.mode || 'DB';
    const op = event.db.op || event.summary || event.subject || 'operation';
    const duration = event.db.duration_ms !== undefined ? ` (${event.db.duration_ms}ms)` : '';
    return `${mode} ${op}${duration}`;
  }
  if (event.draft?.footer) {
    const footer = event.draft.footer;
    const bits = [] as string[];
    if (footer.next) {
      bits.push(`Next: ${footer.next}`);
    }
    if (footer.state) {
      bits.push(footer.state);
    }
    return bits.length ? bits.join(' · ') : 'Draft';
  }
  return '—';
}

function renderWaitState(event: TraceEventRow): string {
  return event.wait_state || '—';
}

function renderStepDetail(event: TraceEventRow): string {
  const parts: string[] = [];
  if (event.step) {
    parts.push(event.step);
  }
  if (event.loop) {
    parts.push('↺');
  }
  if (event.detour_to_step) {
    parts.push(`→ Step ${event.detour_to_step}`);
  }
  return parts.join(' ') || '—';
}

const TraceRow: React.FC<TraceRowProps> = ({ event, isExpanded, onToggle }) => {
  const laneChipClass = laneClass[event.lane] ?? 'lane-chip';
  const laneChipLabel = laneLabel[event.lane] ?? event.lane;
  const statusChipClass = event.status ? statusClass[event.status] : undefined;
  const statusChipLabel = event.status ? statusLabel[event.status] ?? event.status : '';
  const summary = event.summary || event.detail || event.subject || '—';
  const gateCell = renderGateCell(event.gate);
  const entityCell = renderEntityCell(event.entity);
  const ioCell = renderIoCell(event);
  const waitState = renderWaitState(event);
  const stepDetail = renderStepDetail(event);

  return (
    <>
      <tr className="trace-row">
        <td>
          <button
            type="button"
            className="trace-row__chevron"
            aria-expanded={isExpanded}
            onClick={onToggle}
          >
            ▶
          </button>
        </td>
        <td className="trace-row__kind">
          <span className={laneChipClass}>{laneChipLabel}</span>
        </td>
        <td className="trace-row__owner" title={event.ownerLabel || undefined}>
          {event.ownerLabel || '—'}
        </td>
        <td className="trace-row__event">
          <div className="trace-row__event-name">{event.kind}</div>
          {statusChipClass && <span className={statusChipClass}>{statusChipLabel}</span>}
        </td>
        <td className="trace-row__summary" title={summary}>
          {summary}
        </td>
        <td className="trace-row__gate" title={gateCell}>
          {gateCell}
        </td>
        <td className="trace-row__entity" title={typeof entityCell === 'string' ? entityCell : undefined}>
          {entityCell}
        </td>
        <td className="trace-row__io" title={ioCell}>
          {ioCell}
        </td>
        <td className="trace-row__wait" title={waitState}>
          {waitState}
        </td>
        <td className="trace-row__time">{event.formattedTime}</td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={10}>
            <div className="trace-row__details">
              <pre>{JSON.stringify(event.details ?? {}, null, 2)}</pre>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

export default TraceRow;

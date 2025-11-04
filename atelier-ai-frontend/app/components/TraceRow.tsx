import React from 'react';

export interface TraceEventRow {
  index: number;
  thread_id: string;
  ts: number;
  formattedTime: string;
  kind: string;
  lane: string;
  step?: string | null;
  detail?: string | null;
  subject?: string | null;
  status?: string | null;
  summary?: string | null;
  wait_state?: string | null;
  loop?: boolean;
  detour_to_step?: number | null;
  details?: Record<string, unknown> | null;
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

function formatSummary(text?: string | null) {
  if (!text) {
    return '—';
  }
  return text;
}

function formatGateCell(event: TraceEventRow) {
  if (event.lane !== 'gate') {
    return '—';
  }
  const detail = event.detail || event.subject || 'Gate';
  const status = statusLabel[event.status ?? ''] || (event.status ? event.status.toUpperCase() : '');
  const loopMarker = event.loop ? ' ↺' : '';
  return `${detail}: ${status}${loopMarker}`;
}

function formatDbCell(event: TraceEventRow) {
  if (event.lane !== 'db') {
    return '—';
  }
  return event.summary || event.detail || 'DB event';
}

function formatWaitState(event: TraceEventRow) {
  return event.wait_state || '—';
}

function formatStepCell(event: TraceEventRow) {
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
  return parts.join(' ');
}

const TraceRow: React.FC<TraceRowProps> = ({ event, isExpanded, onToggle }) => {
  const laneChip = laneClass[event.lane] ?? 'lane-chip';
  const statusChip = statusClass[event.status ?? ''] ?? '';
  const statusText = statusLabel[event.status ?? ''] ?? event.status ?? '';
  const summaryText = formatSummary(event.summary);

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
        <td className="trace-row__subject" title={event.subject || undefined}>
          <span className={laneChip}>{laneLabel[event.lane] ?? event.lane}</span>
          <span>{event.subject || '—'}</span>
        </td>
        <td>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-800 text-xs">{event.kind}</span>
            {statusChip && <span className={statusChip}>{statusText}</span>}
          </div>
        </td>
        <td className="trace-row__summary" title={formatStepCell(event)}>
          {formatStepCell(event) || '—'}
        </td>
        <td className="trace-row__summary" title={summaryText}>
          {summaryText}
        </td>
        <td className="trace-row__gate" title={formatGateCell(event)}>
          {formatGateCell(event)}
        </td>
        <td className="trace-row__db" title={formatDbCell(event)}>
          {formatDbCell(event)}
        </td>
        <td className="trace-row__wait" title={formatWaitState(event)}>
          {formatWaitState(event)}
        </td>
        <td className="trace-row__time">{event.formattedTime}</td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={9}>
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

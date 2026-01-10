// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';

import TraceTable from '../../trace/TraceTable';
import type { TraceSection, TraceRowData } from '../../trace/TraceTypes';
import type { RawTraceEvent } from '../../debug/utils';

function buildRow(): TraceRowData {
  const raw: RawTraceEvent = {
    thread_id: 'thread-1',
    ts: 1,
    kind: 'STEP_EVENT',
    lane: 'entity',
    step: 'Step3_Room',
    step_major: 3,
    step_minor: 7,
    entity: 'Agent',
    event: 'Emit',
    subloop: 'general_q_a',
  };

  return {
    id: 'row-1',
    timestamp: 1,
    stepMajor: 3,
    stepMinor: 7,
    stepLabel: '3.7',
    stepTitle: 'Step 3 · Room Evaluation',
    stepKey: 'Step3_Room',
    entity: 'AGENT',
    rawEntity: 'Agent',
    actor: 'Agent',
    event: 'Emit',
    functionName: 'run',
    functionPath: 'process.run',
    functionArgs: [],
    valueItems: [],
    gate: undefined,
    io: undefined,
    wait: null,
    timeLabel: '00:00:01',
    prompt: undefined,
    lane: 'entity',
    raw,
    subloop: 'general_q_a',
    subloopLabel: 'Availability overview',
    subloopColor: '#2E77D0',
  };
}

describe('TraceTable subloop styling', () => {
  it('renders subloop tint and badge', () => {
    const row = buildRow();
    const sections: TraceSection[] = [
      {
        key: 'step-3',
        stepMajor: 3,
        title: 'Step 3 · Room Evaluation',
        rows: [row],
      },
    ];

    render(
      <TraceTable
        sections={sections}
        onInspect={() => undefined}
        onTimeTravel={() => undefined}
        hilOpen={false}
        granularity="logic"
      />,
    );

    const badge = screen.getByText('Availability overview');
    expect(badge).toBeInTheDocument();

    const rowElement = badge.closest('.trace-table__row');
    expect(rowElement).not.toBeNull();
    expect(rowElement).toHaveClass('trace-table__row--subloop');
    expect(rowElement).toHaveStyle({ borderLeft: '4px solid #2E77D0' });
  });
});

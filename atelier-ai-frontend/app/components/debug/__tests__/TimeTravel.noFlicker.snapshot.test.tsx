import React from 'react';
import { render } from '@testing-library/react';

import TraceTable from '../../trace/TraceTable';
import type { TraceSection, TraceRowData } from '../../trace/TraceTypes';
import type { RawTraceEvent } from '../../debug/utils';

const baseRaw: RawTraceEvent = {
  thread_id: 'thread-3',
  ts: 10,
  kind: 'STEP_EVENT',
  lane: 'entity',
  step: 'Step3_Room',
  step_major: 3,
  step_minor: 1,
  entity: 'Agent',
  event: 'Emit',
};

const baseRow: TraceRowData = {
  id: 'row-tt',
  timestamp: 10,
  stepMajor: 3,
  stepMinor: 1,
  stepLabel: '3.1',
  stepTitle: 'Step 3 · Room Evaluation',
  stepKey: 'Step3_Room',
  entity: 'AGENT',
  rawEntity: 'Agent',
  actor: 'Agent',
  event: 'Emit',
  functionName: 'run',
  functionArgs: [],
  valueItems: [],
  gate: undefined,
  io: undefined,
  wait: null,
  timeLabel: '00:00:10',
  prompt: undefined,
  lane: 'entity',
  raw: baseRaw,
  subloop: undefined,
  subloopLabel: null,
  subloopColor: null,
};

const sections: TraceSection[] = [
  {
    key: 'step-3',
    stepMajor: 3,
    title: 'Step 3 · Room Evaluation',
    rows: [baseRow],
  },
];

describe('TraceTable time-travel stability', () => {
  it('keeps row structure stable across scrub toggles', () => {
    const { container, rerender } = render(
      <TraceTable
        sections={sections}
        onInspect={() => undefined}
        onTimeTravel={() => undefined}
        hilOpen={false}
        granularity="logic"
        timeTravelStepMajor={null}
        activeTimestamp={null}
      />,
    );

    const rowsInitial = container.querySelectorAll('.trace-table__row');
    expect(rowsInitial.length).toBe(1);

    for (let i = 0; i < 5; i += 1) {
      const activeTs = i % 2 === 0 ? 10 : null;
      const step = i % 2 === 0 ? 3 : null;
      rerender(
        <TraceTable
          sections={sections}
          onInspect={() => undefined}
          onTimeTravel={() => undefined}
          hilOpen={false}
          granularity="logic"
          timeTravelStepMajor={step}
          activeTimestamp={activeTs}
        />,
      );

      const rows = container.querySelectorAll('.trace-table__row');
      expect(rows.length).toBe(1);
      const activeRows = container.querySelectorAll('.trace-table__row--active');
      expect(activeRows.length).toBe(activeTs === null ? 0 : 1);
    }
  });
});

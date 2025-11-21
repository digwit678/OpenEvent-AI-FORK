import { describe, expect, it, vi, afterEach } from 'vitest';

import {
  buildManagerTimeline,
  computeStepProgress,
  createBufferFlusher,
  filterByGranularity,
  type RawTraceEvent,
} from '../utils';

describe('filterByGranularity', () => {
  const baseEvent: RawTraceEvent = {
    thread_id: 'thread',
    ts: 1,
    kind: 'STEP_EVENT',
    lane: 'step',
    step: 'Step1_Intake',
  };

  const sample = [
    { ...baseEvent, entity: 'Trigger', ts: 1 },
    {
      ...baseEvent,
      entity: 'DB Action',
      ts: 2,
      io: { direction: 'write', op: 'insert', result: 'ok' },
    },
    {
      ...baseEvent,
      entity: 'DB Action',
      ts: 3,
      io: { direction: 'read', op: 'select', result: 'ok' },
    },
    { ...baseEvent, entity: 'Waiting', ts: 4 },
  ];

  it('keeps only manager entities for manager granularity', () => {
    const filtered = filterByGranularity(sample, 'manager');
    expect(filtered).toHaveLength(2);
    expect(filtered[0].entity).toBe('Trigger');
    expect(filtered[1].io?.direction).toBe('write');
  });

  it('keeps logic-level entities for logic granularity', () => {
    const filtered = filterByGranularity(sample, 'logic');
    expect(filtered).toHaveLength(4);
    expect(filtered.some((event) => event.entity === 'Waiting')).toBe(true);
  });

  it('returns all events for full granularity', () => {
    expect(filterByGranularity(sample, 'full')).toHaveLength(sample.length);
  });
});

describe('computeStepProgress', () => {
  it('derives gate progress from summary and counters', () => {
    const result = computeStepProgress({
      state: {
        intent: 'event_request',
        number_of_participants: 80,
        chosen_date: '2026-02-14',
        step_counters: {
          Step1_Intake: { met: 2, total: 2 },
          Step3_Room: { met: 2, total: 3 },
        },
      },
      summary: {
        date: { confirmed: true, value: '14.02.2026' },
        room_selected: true,
        requirements_match: false,
        offer_status_display: 'Sent',
      },
    });

    expect(result.Step1_Intake.completed).toBe(2);
    expect(result.Step2_Date.breakdown[1].met).toBe(true);
    expect(result.Step3_Room.breakdown[1].met).toBe(true);
    expect(result.Step4_Offer.breakdown[2].label).toBe('Offer sent');
    expect(result.Step4_Offer.breakdown[2].met).toBe(true);
  });
});

describe('buildManagerTimeline', () => {
  it('sorts events by timestamp and includes gate summary', () => {
    const events: RawTraceEvent[] = [
      {
        thread_id: 'thread',
        ts: 5,
        kind: 'STATE_SNAPSHOT',
        lane: 'step',
        entity: 'Agent',
        event: 'Emit',
        details: 'Responded to client',
      },
      {
        thread_id: 'thread',
        ts: 2,
        kind: 'STEP_EVENT',
        lane: 'step',
        entity: 'Trigger',
        event: 'Receive',
        details: 'Parsed intake',
      },
    ];

    const timeline = buildManagerTimeline(events, {
      Step1_Intake: { completed: 2, total: 2, breakdown: [] },
      Step2_Date: { completed: 1, total: 2, breakdown: [] },
      Step3_Room: { completed: 0, total: 3, breakdown: [] },
      Step4_Offer: { completed: 0, total: 3, breakdown: [] },
    });

    expect(timeline).toHaveLength(2);
    expect(timeline[0]).toContain('Parsed intake');
    expect(timeline[1]).toContain('Responded to client');
  });
});

describe('createBufferFlusher', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('flushes buffered items on animation frame', () => {
    vi.useFakeTimers();
    const onFlush = vi.fn();
    const flusher = createBufferFlusher<string[]>({ onFlush });
    flusher.push(['a', 'b']);
    vi.runOnlyPendingTimers();
    expect(onFlush).toHaveBeenCalledWith(['a', 'b']);
  });

  it('defers flush when paused and resumes afterwards', () => {
    vi.useFakeTimers();
    const onFlush = vi.fn();
    const flusher = createBufferFlusher<string[]>({ onFlush });
    flusher.setPaused(true);
    flusher.push(['pending']);
    vi.runOnlyPendingTimers();
    expect(onFlush).not.toHaveBeenCalled();
    flusher.setPaused(false);
    vi.runOnlyPendingTimers();
    expect(onFlush).toHaveBeenCalledWith(['pending']);
  });
});

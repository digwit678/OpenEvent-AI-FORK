'use client';

import { useEffect, useState, useMemo } from 'react';
import StepFilter, { useStepFilter } from './StepFilter';

function extractStepNumber(step: string): number | null {
  const match = step.match(/step[_\s]?(\d+)/i);
  return match ? parseInt(match[1], 10) : null;
}

interface DateEvent {
  ts: number;
  step: string;
  event_type: string;
  raw_input?: string;
  parsed_value?: string;
  stored_value?: string;
  parser_used?: string;
  mismatch?: boolean;
}

interface DateTrailViewProps {
  threadId: string | null;
  pollMs?: number;
}

interface RawTraceEvent {
  ts?: number;
  kind?: string;
  step?: string;
  owner_step?: string;
  subject?: string;
  data?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  entity_context?: Record<string, unknown>;
}

export default function DateTrailView({ threadId, pollMs = 2000 }: DateTrailViewProps) {
  const [events, setEvents] = useState<DateEvent[]>([]);
  const [currentDate, setCurrentDate] = useState<string | null>(null);
  const [dateConfirmed, setDateConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { selectedStep } = useStepFilter();

  // Filter events by selected step
  const filteredEvents = useMemo(() => {
    if (selectedStep === null) return events;
    return events.filter((event) => {
      const stepNum = extractStepNumber(event.step);
      return stepNum === selectedStep;
    });
  }, [events, selectedStep]);

  // Get available steps
  const availableSteps = useMemo(() => {
    const steps = new Set<number>();
    events.forEach((event) => {
      const stepNum = extractStepNumber(event.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    return Array.from(steps).sort((a, b) => a - b);
  }, [events]);

  useEffect(() => {
    if (!threadId) {
      setEvents([]);
      setCurrentDate(null);
      setDateConfirmed(false);
      return;
    }

    const controller = new AbortController();
    const fetchData = async () => {
      try {
        const response = await fetch(
          `/api/debug/threads/${encodeURIComponent(threadId)}?granularity=verbose`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = await response.json();
        const state = payload.state || {};
        const trace = payload.trace || [];

        setCurrentDate((state.chosen_date as string) || null);
        setDateConfirmed(Boolean(state.date_confirmed));

        // Extract date-related events
        const dateEvents = extractDateEvents(trace, state);
        setEvents(dateEvents);
        setError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      }
    };

    fetchData();
    const interval = setInterval(fetchData, pollMs);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [threadId, pollMs]);

  if (!threadId) {
    return (
      <div className="p-8 text-center text-slate-400">
        No thread connected. Go back to the dashboard to connect.
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StepFilter availableSteps={availableSteps} />

      {/* Current Date Status */}
      <div className={`p-4 rounded-lg border ${
        dateConfirmed
          ? 'bg-green-500/10 border-green-500/30'
          : 'bg-yellow-500/10 border-yellow-500/30'
      }`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-slate-400">Current Date</div>
            <div className="text-xl font-semibold">
              {currentDate || '(not set)'}
            </div>
          </div>
          <div className={`px-3 py-1 rounded-full text-sm font-medium ${
            dateConfirmed
              ? 'bg-green-500/20 text-green-400'
              : 'bg-yellow-500/20 text-yellow-400'
          }`}>
            {dateConfirmed ? '\u2713 Confirmed' : 'Pending'}
          </div>
        </div>
      </div>

      {/* Date Trail Timeline */}
      <div>
        <h2 className="text-lg font-semibold mb-3">
          Date Transformation Trail
          {selectedStep !== null && (
            <span className="text-sm font-normal text-slate-400 ml-2">
              ({filteredEvents.length} of {events.length})
            </span>
          )}
        </h2>
        {filteredEvents.length === 0 ? (
          <div className="text-slate-400 text-sm">No date events recorded yet.</div>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-slate-700" />

            <div className="space-y-4">
              {filteredEvents.map((event, idx) => {
                const stepNum = extractStepNumber(event.step);
                return (
                <div key={idx} id={stepNum !== null ? `step-${stepNum}` : undefined} className="relative pl-10">
                  {/* Timeline dot */}
                  <div className={`absolute left-2.5 w-3 h-3 rounded-full ${
                    event.mismatch
                      ? 'bg-red-500'
                      : event.event_type === 'confirmed'
                      ? 'bg-green-500'
                      : 'bg-blue-500'
                  }`} />

                  <div className={`p-4 rounded-lg border ${
                    event.mismatch
                      ? 'bg-red-500/10 border-red-500/30'
                      : 'bg-slate-800/50 border-slate-700'
                  }`}>
                    {/* Header */}
                    <div className="flex items-center gap-3 mb-2">
                      <span className="text-xs text-slate-500 font-mono">
                        {formatTime(event.ts)}
                      </span>
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                        {event.step}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        event.event_type === 'captured'
                          ? 'bg-blue-500/20 text-blue-400'
                          : event.event_type === 'confirmed'
                          ? 'bg-green-500/20 text-green-400'
                          : event.event_type === 'parsed'
                          ? 'bg-purple-500/20 text-purple-400'
                          : 'bg-slate-700 text-slate-300'
                      }`}>
                        {event.event_type}
                      </span>
                      {event.mismatch && (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400">
                          MISMATCH
                        </span>
                      )}
                    </div>

                    {/* Details */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                      {event.raw_input && (
                        <div>
                          <div className="text-xs text-slate-500 mb-1">Raw Input</div>
                          <div className="text-slate-300 font-mono bg-slate-900/50 p-2 rounded">
                            {event.raw_input}
                          </div>
                        </div>
                      )}
                      {event.parsed_value && (
                        <div>
                          <div className="text-xs text-slate-500 mb-1">Parsed Value</div>
                          <div className="text-slate-300 font-mono bg-slate-900/50 p-2 rounded">
                            {event.parsed_value}
                          </div>
                        </div>
                      )}
                      {event.stored_value && (
                        <div>
                          <div className="text-xs text-slate-500 mb-1">Stored Value</div>
                          <div className={`font-mono p-2 rounded ${
                            event.mismatch
                              ? 'text-red-400 bg-red-900/20'
                              : 'text-slate-300 bg-slate-900/50'
                          }`}>
                            {event.stored_value}
                          </div>
                        </div>
                      )}
                      {event.parser_used && (
                        <div>
                          <div className="text-xs text-slate-500 mb-1">Parser Used</div>
                          <div className="text-slate-400 text-xs">
                            {event.parser_used}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function extractDateEvents(trace: RawTraceEvent[], state: Record<string, unknown>): DateEvent[] {
  const events: DateEvent[] = [];
  const storedDate = state.chosen_date as string | undefined;

  trace.forEach((event) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};
    const entityCtx = event.entity_context || {};

    // Look for date-related entity captures
    if (kind === 'ENTITY_CAPTURE' || kind === 'ENTITY_SUPERSEDED') {
      const key = (entityCtx.key as string) || event.subject || '';
      if (key.toLowerCase().includes('date') || key === 'chosen_date' || key === 'event_date') {
        const value = entityCtx.value as string | undefined;
        events.push({
          ts: event.ts || 0,
          step: event.step || event.owner_step || '',
          event_type: kind === 'ENTITY_CAPTURE' ? 'captured' : 'superseded',
          raw_input: data.source_text as string | undefined,
          parsed_value: value,
          stored_value: value,
          parser_used: data.parser_used as string | undefined,
          mismatch: storedDate ? value !== storedDate : false,
        });
      }
    }

    // Look for date confirmation events
    if (kind === 'DB_WRITE' && (event.subject || '').toLowerCase().includes('date')) {
      events.push({
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        event_type: 'confirmed',
        stored_value: data.date as string | undefined || data.chosen_date as string | undefined,
      });
    }

    // Look for date lifecycle events (from new trace hook)
    if (kind === 'DATE_LIFECYCLE') {
      events.push({
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        event_type: data.event as string || 'lifecycle',
        raw_input: data.raw_input as string | undefined,
        parsed_value: data.parsed_value as string | undefined,
        stored_value: data.storage_value as string | undefined,
        parser_used: data.parser_used as string | undefined,
        mismatch: data.mismatch as boolean | undefined,
      });
    }
  });

  return events.reverse(); // Most recent first
}

function formatTime(ts: number): string {
  if (!ts) return '--:--:--';
  try {
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString('en-GB', { hour12: false });
  } catch {
    return '--:--:--';
  }
}

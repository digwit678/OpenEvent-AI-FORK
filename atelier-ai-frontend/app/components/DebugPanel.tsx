'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import TraceRow, { TraceEventRow } from './TraceRow';
import TraceLegend from './TraceLegend';
import TimelineToolbar from './TimelineToolbar';

const LANES = ['step', 'gate', 'db', 'entity', 'detour', 'qa', 'draft'] as const;
const STATUSES = ['captured', 'confirmed', 'changed', 'checked', 'pass', 'fail'] as const;

type Lane = (typeof LANES)[number];

type TraceStatus = (typeof STATUSES)[number] | string | undefined;

interface TraceEvent {
  thread_id: string;
  ts: number;
  kind: string;
  lane: Lane | string;
  step?: string | null;
  detail?: string | null;
  subject?: string | null;
  status?: TraceStatus;
  summary?: string | null;
  wait_state?: string | null;
  loop?: boolean;
  detour_to_step?: number | null;
  details?: Record<string, unknown> | null;
  data?: Record<string, unknown> | null;
}

interface ConfirmedMap {
  date: boolean;
  room_locked: boolean;
  requirements_hash_matches: boolean;
}

interface TraceResponse {
  thread_id: string;
  state: Record<string, unknown>;
  confirmed?: ConfirmedMap;
  trace: TraceEvent[];
}

interface DebugPanelProps {
  threadId: string | null;
  pollMs?: number;
}

function formatTime(timestamp: number): string {
  try {
    return new Date(timestamp * 1000).toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (error) {
    return timestamp.toFixed(2);
  }
}

function createFilterMap(keys: readonly string[]): Record<string, boolean> {
  return keys.reduce<Record<string, boolean>>((acc, key) => {
    acc[key] = true;
    return acc;
  }, {});
}

function hasFooterMeta(details?: Record<string, unknown> | null): boolean {
  if (!details) {
    return false;
  }
  const footer = details.footer as Record<string, unknown> | undefined;
  if (!footer) {
    return false;
  }
  return Boolean(footer.step && footer.next && footer.wait_state);
}

export default function DebugPanel({ threadId, pollMs = 1500 }: DebugPanelProps) {
  const [tracePayload, setTracePayload] = useState<TraceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [laneFilters, setLaneFilters] = useState<Record<string, boolean>>(() => createFilterMap(LANES));
  const [statusFilters, setStatusFilters] = useState<Record<string, boolean>>(() => createFilterMap(STATUSES));
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const tableBodyRef = useRef<HTMLDivElement | null>(null);

  const handleDownloadJson = useCallback(() => {
    if (!threadId) {
      return;
    }
    const url = `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/download`;
    window.open(url, '_blank');
  }, [threadId]);

  const handleDownloadArrow = useCallback(() => {
    if (!threadId) {
      return;
    }
    const url = `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/text`;
    window.open(url, '_blank');
  }, [threadId]);

  useEffect(() => {
    if (!threadId) {
      setTracePayload(null);
      setError('Waiting for session to start…');
      return;
    }

    if (paused) {
      return;
    }

    let isCancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    const fetchTrace = async () => {
      try {
        const response = await fetch(`/api/debug/threads/${encodeURIComponent(threadId)}`);
        if (response.status === 404) {
          setDisabled(true);
          setError('Tracing disabled. Ensure DEBUG_TRACE is unset or set to 1, then restart the server.');
          if (timer) {
            clearInterval(timer);
          }
          return;
        }
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = (await response.json()) as TraceResponse;
        if (!isCancelled) {
          setTracePayload(payload);
          setError(null);
        }
      } catch (err) {
        if (isCancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load trace');
      }
    };

    fetchTrace();
    timer = setInterval(fetchTrace, pollMs);

    return () => {
      isCancelled = true;
      if (timer) {
        clearInterval(timer);
      }
    };
  }, [threadId, pollMs, paused]);

  const rawRows = useMemo<TraceEventRow[]>(() => {
    if (!tracePayload) {
      return [];
    }
    return tracePayload.trace.map((event, index) => {
      const lane = (event.lane || 'step').toString().toLowerCase();
      const details = (event.details ?? event.data ?? {}) as Record<string, unknown>;
      const waitState = event.wait_state ?? (typeof details.wait_state === 'string' ? (details.wait_state as string) : undefined);
      return {
        index: index + 1,
        thread_id: event.thread_id,
        ts: event.ts,
        formattedTime: formatTime(event.ts),
        kind: event.kind,
        lane,
        step: event.step,
        detail: event.detail,
        subject: event.subject ?? event.step ?? event.kind,
        status: event.status,
        summary: event.summary ?? (typeof details.summary === 'string' ? (details.summary as string) : undefined),
        wait_state: waitState ?? null,
        loop: Boolean(event.loop),
        detour_to_step: typeof event.detour_to_step === 'number' ? event.detour_to_step : null,
        details,
      };
    });
  }, [tracePayload]);

  const limitedRows = useMemo(() => {
    if (rawRows.length <= 500) {
      return rawRows;
    }
    return rawRows.slice(-500);
  }, [rawRows]);

  const filteredRows = useMemo(() => {
    return limitedRows.filter((row) => {
      const laneEnabled = laneFilters[row.lane] ?? true;
      if (!laneEnabled) {
        return false;
      }
      const statusKey = row.status ? row.status.toString().toLowerCase() : 'captured';
      const statusEnabled = statusFilters[statusKey] ?? true;
      return statusEnabled;
    });
  }, [limitedRows, laneFilters, statusFilters]);

  useEffect(() => {
    if (!autoScroll || !tableBodyRef.current) {
      return;
    }
    tableBodyRef.current.scrollTop = tableBodyRef.current.scrollHeight;
  }, [filteredRows.length, autoScroll]);

  const lastDraft = useMemo(() => {
    for (let i = rawRows.length - 1; i >= 0; i -= 1) {
      if (rawRows[i].lane === 'draft') {
        return rawRows[i];
      }
    }
    return null;
  }, [rawRows]);

  const missingFooter = lastDraft ? !hasFooterMeta(lastDraft.details) : false;

  const confirmed = tracePayload?.confirmed;

  const toggleRow = useCallback((index: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  const handleLaneToggle = useCallback((lane: string) => {
    setLaneFilters((prev) => ({
      ...prev,
      [lane]: !prev[lane],
    }));
  }, []);

  const handleStatusToggle = useCallback((status: string) => {
    setStatusFilters((prev) => ({
      ...prev,
      [status]: !prev[status],
    }));
  }, []);

  const timelineEmpty = !tracePayload || filteredRows.length === 0;

  return (
    <div className="bg-white border border-gray-200 rounded-2xl shadow-xl overflow-hidden h-[calc(100vh-160px)] flex flex-col">
      <div className="px-4 py-3 bg-gray-900 text-gray-100 sticky top-0 z-10 flex items-center justify-between gap-2">
        <div className="font-semibold text-sm">Workflow Debugger</div>
        <div className="flex items-center gap-2">
          <span className="text-xs opacity-75">{threadId || 'no-thread'}</span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
        {disabled && (
          <div className="p-3 bg-yellow-50 border border-yellow-200 text-yellow-800 rounded">
            {error || 'Debug trace disabled.'}
          </div>
        )}
        {!disabled && error && (
          <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded">{error}</div>
        )}
        {!disabled && !error && !tracePayload && (
          <div className="p-3 bg-blue-50 border border-blue-200 text-blue-700 rounded">
            Waiting for trace events…
          </div>
        )}

        {!disabled && tracePayload && (
          <>
            <div className="space-y-3">
              <div className="trace-card">
                <div className="trace-card__title">Thread State Snapshot</div>
                {Object.keys(tracePayload.state || {}).length === 0 ? (
                  <div className="text-xs text-gray-500">No snapshot captured yet.</div>
                ) : (
                  <dl className="text-xs grid grid-cols-1 gap-1">
                    {Object.entries(tracePayload.state).map(([key, value]) => (
                      <div key={key} className="flex justify-between gap-2">
                        <dt className="text-gray-500">{key}</dt>
                        <dd className="font-mono text-gray-800 text-right">{String(value)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {missingFooter && (
                  <div className="mt-3">
                    <span className="trace-warning">⚠ Missing footer metadata on last draft</span>
                  </div>
                )}
              </div>

              {confirmed && (
                <div className="trace-card">
                  <div className="trace-card__title">Confirmation Signals</div>
                  <div className="trace-card__grid">
                    <span className={`trace-card__pill ${confirmed.date ? 'trace-card__pill--ok' : 'trace-card__pill--pending'}`}>
                      Date {confirmed.date ? 'Confirmed' : 'Pending'}
                    </span>
                    <span className={`trace-card__pill ${confirmed.room_locked ? 'trace-card__pill--ok' : 'trace-card__pill--pending'}`}>
                      Room {confirmed.room_locked ? 'Locked' : 'Open'}
                    </span>
                    <span className={`trace-card__pill ${confirmed.requirements_hash_matches ? 'trace-card__pill--ok' : 'trace-card__pill--pending'}`}>
                      Hash {confirmed.requirements_hash_matches ? 'Aligned' : 'Mismatch'}
                    </span>
                  </div>
                </div>
              )}

              <TraceLegend />
              <TimelineToolbar
                autoScroll={autoScroll}
                paused={paused}
                onToggleAutoScroll={() => setAutoScroll((prev) => !prev)}
                onTogglePaused={() => setPaused((prev) => !prev)}
                laneFilters={laneFilters}
                onLaneToggle={handleLaneToggle}
                statusFilters={statusFilters}
                onStatusToggle={handleStatusToggle}
                onDownloadJson={handleDownloadJson}
                onDownloadText={handleDownloadArrow}
              />
            </div>

            {rawRows.length > 500 && (
              <div className="text-[11px] text-gray-500">Showing the latest 500 of {rawRows.length} events.</div>
            )}

            <div className="border border-gray-200 rounded-lg bg-white relative">
              <div className="trace-table__body" ref={tableBodyRef}>
                <table className="trace-table">
                  <thead>
                    <tr>
                      <th className="w-10" aria-label="Toggle" />
                      <th>Subject</th>
                      <th>Event</th>
                      <th>Step / Flow</th>
                      <th>Summary</th>
                      <th>Gatekeeping</th>
                      <th>DB I/O</th>
                      <th>Wait State</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {timelineEmpty ? (
                      <tr>
                        <td colSpan={9} className="text-center text-xs text-gray-500 py-4">
                          No trace events yet.
                        </td>
                      </tr>
                    ) : (
                      filteredRows.map((event) => (
                        <TraceRow
                          key={`${event.thread_id}-${event.index}-${event.ts}`}
                          event={event}
                          isExpanded={expandedRows.has(event.index)}
                          onToggle={() => toggleRow(event.index)}
                        />
                      ))
                    )}
                  </tbody>
                </table>
                <div className="trace-table__fade" />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

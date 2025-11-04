'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import TraceRow, {
  TraceEventRow,
  GateInfo,
  EntityInfo,
  DbInfo,
  DraftInfo,
} from './TraceRow';
import TraceLegend from './TraceLegend';
import TimelineToolbar from './TimelineToolbar';

const LANES = ['step', 'gate', 'db', 'entity', 'detour', 'qa', 'draft'] as const;

const STEP_ORDER = ['Step1_Intake', 'Step2_Date', 'Step3_Room', 'Step4_Offer'] as const;

const STEP_LABELS: Record<string, string> = {
  Step1_Intake: 'Intake',
  Step2_Date: 'Date Confirmation',
  Step3_Room: 'Room Availability',
  Step4_Offer: 'Offer',
};

const STEP_FROM_NUMBER: Record<number, string> = {
  1: 'Step1_Intake',
  2: 'Step2_Date',
  3: 'Step3_Room',
  4: 'Step4_Offer',
};

interface TraceEvent {
  thread_id: string;
  ts: number;
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
  data?: Record<string, unknown> | null;
  owner_step?: string | null;
  granularity?: string | null;
  gate?: GateInfo | null;
  entity?: EntityInfo | null;
  db?: DbInfo | null;
  detour?: Record<string, unknown> | null;
  draft?: DraftInfo | null;
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

type Lane = (typeof LANES)[number];
type StepKey = (typeof STEP_ORDER)[number];

type Granularity = 'logic' | 'verbose';

type PrereqResult = {
  label: string;
  value: string;
  status: 'ok' | 'pending';
};

type PrereqResolver = (state: Record<string, unknown>, confirmed?: ConfirmedMap) => PrereqResult;

const STEP_PREREQS: Record<StepKey, PrereqResolver[]> = {
  Step1_Intake: [
    (state) => ({
      label: 'Intent',
      value: String(state.intent || state.intent_label || '—'),
      status: state.intent ? 'ok' : 'pending',
    }),
    (state) => ({
      label: 'Participants',
      value: state.participants ? String(state.participants) : '—',
      status: state.participants ? 'ok' : 'pending',
    }),
  ],
  Step2_Date: [
    (state, confirmed) => ({
      label: 'Chosen Date',
      value: state.chosen_date ? String(state.chosen_date) : '—',
      status: state.chosen_date ? 'ok' : 'pending',
    }),
    (state, confirmed) => ({
      label: 'Date Confirmed',
      value: confirmed?.date ? 'Confirmed' : 'Pending',
      status: confirmed?.date ? 'ok' : 'pending',
    }),
  ],
  Step3_Room: [
    (state, confirmed) => ({
      label: 'Date Confirmed',
      value: confirmed?.date ? 'Yes' : 'No',
      status: confirmed?.date ? 'ok' : 'pending',
    }),
    (state, confirmed) => ({
      label: 'Locked Room',
      value: state.locked_room_id ? String(state.locked_room_id) : 'Open',
      status: confirmed?.room_locked ? 'ok' : 'pending',
    }),
    (state, confirmed) => ({
      label: 'Hash Match',
      value: confirmed?.requirements_hash_matches ? 'Match' : 'Mismatch',
      status: confirmed?.requirements_hash_matches ? 'ok' : 'pending',
    }),
  ],
  Step4_Offer: [
    (state) => ({
      label: 'Offer ID',
      value: state.current_offer_id ? String(state.current_offer_id) : 'None',
      status: state.current_offer_id ? 'ok' : 'pending',
    }),
    (state) => ({
      label: 'Offer Status',
      value: state.offer_status ? String(state.offer_status) : 'Draft',
      status: state.offer_status && String(state.offer_status).toLowerCase() === 'sent' ? 'ok' : 'pending',
    }),
  ],
};

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

function getStepLabel(ownerStep?: string | null): string {
  if (!ownerStep) {
    return 'Global';
  }
  return STEP_LABELS[ownerStep] || ownerStep;
}

function resolveCurrentStep(state: Record<string, unknown>): string | null {
  const numeric = typeof state.current_step === 'number' ? state.current_step : undefined;
  if (numeric && STEP_FROM_NUMBER[numeric]) {
    return STEP_FROM_NUMBER[numeric];
  }
  const stepName = typeof state.step === 'string' ? state.step : undefined;
  if (stepName && STEP_LABELS[stepName]) {
    return stepName;
  }
  return null;
}

function resolveCallerStep(state: Record<string, unknown>): string | null {
  const numeric = typeof state.caller_step === 'number' ? state.caller_step : undefined;
  if (numeric && STEP_FROM_NUMBER[numeric]) {
    return STEP_FROM_NUMBER[numeric];
  }
  const stepName = typeof state.caller_step === 'string' ? state.caller_step : undefined;
  if (stepName && STEP_LABELS[stepName]) {
    return stepName;
  }
  return null;
}

function applyPrereqs(stepKey: StepKey, state: Record<string, unknown>, confirmed?: ConfirmedMap): PrereqResult[] {
  return STEP_PREREQS[stepKey].map((resolver) => resolver(state, confirmed));
}

function summarizeSignal(value: string, status: 'ok' | 'pending'): string {
  return value || (status === 'ok' ? 'Ready' : 'Pending');
}

export default function DebugPanel({ threadId, pollMs = 1500 }: DebugPanelProps) {
  const [tracePayload, setTracePayload] = useState<TraceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [granularity, setGranularity] = useState<Granularity>('logic');
  const [laneFilters, setLaneFilters] = useState<Record<string, boolean>>(() => createFilterMap(LANES));
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const mainScrollRef = useRef<HTMLDivElement | null>(null);

  const activeKinds = useMemo(
    () => Object.entries(laneFilters).filter(([, enabled]) => enabled).map(([lane]) => lane),
    [laneFilters],
  );

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    params.set('granularity', granularity);
    if (activeKinds.length && activeKinds.length < LANES.length) {
      params.set('kinds', activeKinds.join(','));
    }
    const built = params.toString();
    return built ? `?${built}` : '';
  }, [granularity, activeKinds]);

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
        const response = await fetch(`/api/debug/threads/${encodeURIComponent(threadId)}${queryString}`);
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
  }, [threadId, pollMs, paused, queryString]);

  const handleDownloadJson = useCallback(() => {
    if (!threadId) {
      return;
    }
    window.open(`/api/debug/threads/${encodeURIComponent(threadId)}/timeline/download${queryString}`, '_blank');
  }, [threadId, queryString]);

  const handleDownloadReadable = useCallback(() => {
    if (!threadId) {
      return;
    }
    window.open(`/api/debug/threads/${encodeURIComponent(threadId)}/timeline/text${queryString}`, '_blank');
  }, [threadId, queryString]);

  const laneToggle = useCallback((lane: string) => {
    setLaneFilters((prev) => {
      const activeCount = Object.values(prev).filter(Boolean).length;
      const currentlyEnabled = !!prev[lane];
      if (currentlyEnabled && activeCount <= 1) {
        return prev;
      }
      return {
        ...prev,
        [lane]: !currentlyEnabled,
      };
    });
  }, []);

  const stateRecord = (tracePayload?.state || {}) as Record<string, unknown>;
  const confirmed = tracePayload?.confirmed;

  const rawRows = useMemo<TraceEventRow[]>(() => {
    if (!tracePayload) {
      return [];
    }
    return tracePayload.trace.map((event, index) => {
      const ownerStep = event.owner_step || event.step || null;
      const ownerLabel = getStepLabel(ownerStep || undefined);
      const lane = (event.lane || 'step').toString().toLowerCase();
      const details = (event.details ?? event.data ?? {}) as Record<string, unknown>;
      return {
        index: index + 1,
        thread_id: event.thread_id,
        ts: event.ts,
        formattedTime: formatTime(event.ts),
        kind: event.kind,
        lane,
        ownerStep,
        ownerLabel,
        step: event.step,
        detail: event.detail,
        subject: event.subject ?? event.step ?? event.kind,
        status: event.status ?? undefined,
        summary: event.summary ?? (typeof details.summary === 'string' ? (details.summary as string) : undefined),
        wait_state: event.wait_state ?? undefined,
        loop: Boolean(event.loop),
        detour_to_step: typeof event.detour_to_step === 'number' ? event.detour_to_step : null,
        details,
        gate: event.gate ?? undefined,
        entity: event.entity ?? undefined,
        db: event.db ?? undefined,
        draft: event.draft ?? undefined,
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
    return limitedRows.filter((row) => laneFilters[row.lane] !== false);
  }, [limitedRows, laneFilters]);

  useEffect(() => {
    if (!autoScroll || !mainScrollRef.current) {
      return;
    }
    mainScrollRef.current.scrollTop = mainScrollRef.current.scrollHeight;
  }, [filteredRows.length, autoScroll]);

  const groupedRows = useMemo(() => {
    const groups: Record<string, TraceEventRow[]> = {};
    filteredRows.forEach((row) => {
      const key = row.ownerStep || 'Global';
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(row);
    });
    return groups;
  }, [filteredRows]);

  const globalRows = groupedRows.Global || [];

  const entitySnapshots = useMemo(() => {
    const captured = new Map<string, EntityInfo>();
    const confirmedEntities = new Map<string, EntityInfo>();
    filteredRows.forEach((row) => {
      if (!row.entity || !row.entity.key) {
        return;
      }
      const key = String(row.entity.key);
      if (row.entity.lifecycle === 'confirmed') {
        confirmedEntities.set(key, row.entity);
      } else {
        captured.set(key, row.entity);
      }
    });
    return {
      captured: Array.from(captured.values()),
      confirmed: Array.from(confirmedEntities.values()),
    };
  }, [filteredRows]);

  const currentStepKey = resolveCurrentStep(stateRecord);
  const currentStepLabel = currentStepKey ? STEP_LABELS[currentStepKey] || currentStepKey : '—';
  const callerStepKey = resolveCallerStep(stateRecord);
  const callerStepLabel = callerStepKey ? STEP_LABELS[callerStepKey] || callerStepKey : '—';
  const waitState = stateRecord.thread_state ? String(stateRecord.thread_state) : '—';

  const signals = useMemo(() => {
    const chosenDate = stateRecord.chosen_date ? String(stateRecord.chosen_date) : '—';
    const dateSignal: PrereqResult = {
      label: 'Date Confirmed',
      value: chosenDate,
      status: confirmed?.date ? 'ok' : 'pending',
    };
    const roomSignal: PrereqResult = {
      label: 'Room Lock',
      value: stateRecord.locked_room_id ? String(stateRecord.locked_room_id) : 'Open',
      status: confirmed?.room_locked ? 'ok' : 'pending',
    };
    const hashSignal: PrereqResult = {
      label: 'Hash Match',
      value: confirmed?.requirements_hash_matches ? 'Match' : 'Mismatch',
      status: confirmed?.requirements_hash_matches ? 'ok' : 'pending',
    };
    const offerSignal: PrereqResult = {
      label: 'Offer',
      value: stateRecord.current_offer_id ? String(stateRecord.current_offer_id) : 'Not sent',
      status:
        stateRecord.offer_status && String(stateRecord.offer_status).toLowerCase() === 'sent'
          ? 'ok'
          : stateRecord.current_offer_id
          ? 'ok'
          : 'pending',
    };
    return [dateSignal, roomSignal, hashSignal, offerSignal];
  }, [stateRecord, confirmed]);

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

  const handleGranularityChange = useCallback((value: Granularity) => {
    setGranularity(value);
  }, []);

  const missingFooterWarning = useMemo(() => {
    for (let i = filteredRows.length - 1; i >= 0; i -= 1) {
      const row = filteredRows[i];
      if (row.lane === 'draft') {
        const footer = row.draft?.footer;
        return !(footer?.step && footer?.next && footer?.state);
      }
    }
    return false;
  }, [filteredRows]);

  const renderPrereqs = useCallback(
    (stepKey: StepKey) => {
      const prereqs = applyPrereqs(stepKey, stateRecord, confirmed);
      return (
        <div className="trace-prereqs">
          {prereqs.map((item) => (
            <span
              key={item.label}
              className={`trace-prereq-pill trace-prereq-pill--${item.status}`}
              title={`${item.label}: ${item.value}`}
            >
              <span className="trace-prereq-pill__label">{item.label}</span>
              <span className="trace-prereq-pill__value">{item.value}</span>
            </span>
          ))}
        </div>
      );
    },
    [stateRecord, confirmed],
  );

  const timelineEmpty = filteredRows.length === 0;

  return (
    <div className="debug-panel">
      <div className="debug-panel__header">
        <div className="debug-panel__thread">Thread: {threadId || '—'}</div>
        <div className="debug-panel__meta">
          <span>Current Step: {currentStepLabel}</span>
          <span>Wait State: {waitState}</span>
          <span>Caller Step: {callerStepLabel}</span>
        </div>
      </div>
      <div className="debug-panel__content">
        <div className="debug-panel__main" ref={mainScrollRef}>
          {disabled && (
            <div className="trace-alert trace-alert--warning">
              {error || 'Debug trace disabled.'}
            </div>
          )}
          {!disabled && error && <div className="trace-alert trace-alert--error">{error}</div>}
          {!disabled && !error && !tracePayload && (
            <div className="trace-alert trace-alert--info">Waiting for trace events…</div>
          )}

          {tracePayload && (
            <>
              <div className="trace-signal-ribbon">
                {signals.map((signal) => (
                  <span
                    key={signal.label}
                    className={`trace-signal trace-signal--${signal.status}`}
                    title={`${signal.label}: ${signal.value}`}
                  >
                    <span className="trace-signal__label">{signal.label}</span>
                    <span className="trace-signal__value">{summarizeSignal(signal.value, signal.status)}</span>
                  </span>
                ))}
              </div>

              <div className="trace-card">
                <div className="trace-card__title">Thread State Snapshot</div>
                {Object.keys(stateRecord).length === 0 ? (
                  <div className="text-xs text-gray-500">No snapshot captured yet.</div>
                ) : (
                  <dl className="trace-state-grid">
                    {Object.entries(stateRecord).map(([key, value]) => (
                      <div key={key} className="trace-state-grid__item">
                        <dt>{key}</dt>
                        <dd>{String(value)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {missingFooterWarning && (
                  <div className="trace-warning">⚠ Missing footer metadata on last draft</div>
                )}
              </div>

              <TraceLegend />
              <TimelineToolbar
                autoScroll={autoScroll}
                paused={paused}
                onToggleAutoScroll={() => setAutoScroll((prev) => !prev)}
                onTogglePaused={() => setPaused((prev) => !prev)}
                selectedKinds={activeKinds}
                onKindToggle={laneToggle}
                granularity={granularity}
                onGranularityChange={handleGranularityChange}
                onDownloadJson={handleDownloadJson}
                onDownloadText={handleDownloadReadable}
              />

              {rawRows.length > 500 && (
                <div className="trace-note">Showing the latest 500 of {rawRows.length} events.</div>
              )}

              {STEP_ORDER.map((stepKey) => {
                const groupRowsForStep = groupedRows[stepKey] || [];
                if (groupRowsForStep.length === 0 && granularity === 'logic') {
                  // Skip empty groups in logic mode for brevity.
                  return null;
                }
                return (
                  <section key={stepKey} className="trace-group">
                    <header className="trace-group__header">
                      <div className="trace-group__title">{STEP_LABELS[stepKey]}</div>
                      {renderPrereqs(stepKey)}
                    </header>
                    <div className="trace-group__table">
                      <table className="trace-table">
                        <thead>
                          <tr>
                            <th className="w-10" aria-label="Expand" />
                            <th className="w-28">Kind</th>
                            <th className="w-32">Owner</th>
                            <th className="w-36">Event</th>
                            <th className="w-52">Summary</th>
                            <th className="w-56">Gate</th>
                            <th className="w-48">Entities</th>
                            <th className="w-48">I/O</th>
                            <th className="w-32">Wait</th>
                            <th className="w-24">Time</th>
                          </tr>
                        </thead>
                        <tbody>
                          {groupRowsForStep.length === 0 ? (
                            <tr>
                              <td colSpan={10} className="trace-table__empty">
                                No events recorded for this step.
                              </td>
                            </tr>
                          ) : (
                            groupRowsForStep.map((event) => (
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
                    </div>
                  </section>
                );
              })}

              {globalRows.length > 0 && (
                <section className="trace-group">
                  <header className="trace-group__header">
                    <div className="trace-group__title">Global Events</div>
                  </header>
                  <div className="trace-group__table">
                    <table className="trace-table">
                      <thead>
                        <tr>
                          <th className="w-10" aria-label="Expand" />
                          <th className="w-28">Kind</th>
                          <th className="w-32">Owner</th>
                          <th className="w-36">Event</th>
                          <th className="w-52">Summary</th>
                          <th className="w-56">Gate</th>
                          <th className="w-48">Entities</th>
                          <th className="w-48">I/O</th>
                          <th className="w-32">Wait</th>
                          <th className="w-24">Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {globalRows.map((event) => (
                          <TraceRow
                            key={`${event.thread_id}-${event.index}-${event.ts}`}
                            event={event}
                            isExpanded={expandedRows.has(event.index)}
                            onToggle={() => toggleRow(event.index)}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {timelineEmpty && <div className="trace-alert trace-alert--info">No trace events yet.</div>}
            </>
          )}
        </div>

        <aside className="trace-sidebar">
          <div className="trace-card">
            <div className="trace-card__title">Tracked Entities</div>
            <div className="trace-entities">
              <div>
                <div className="trace-entities__label">Captured</div>
                {entitySnapshots.captured.length === 0 ? (
                  <div className="trace-entities__empty">None</div>
                ) : (
                  entitySnapshots.captured.map((entity, idx) => (
                    <span key={`${entity.key}-${idx}`} className="entity-badge entity-badge--captured">
                      {`${entity.key}=${String(entity.value ?? '—')}`}
                    </span>
                  ))
                )}
              </div>
              <div>
                <div className="trace-entities__label">Confirmed</div>
                {entitySnapshots.confirmed.length === 0 ? (
                  <div className="trace-entities__empty">None</div>
                ) : (
                  entitySnapshots.confirmed.map((entity, idx) => (
                    <span key={`${entity.key}-${idx}`} className="entity-badge entity-badge--confirmed">
                      {`${entity.key}=${String(entity.value ?? '—')}`}
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

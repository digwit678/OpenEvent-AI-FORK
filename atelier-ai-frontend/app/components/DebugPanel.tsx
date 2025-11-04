'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Toolbar from './debug/Toolbar';
import ManagerView from './debug/ManagerView';
import {
  buildManagerTimeline,
  computeStepProgress,
  createBufferFlusher,
  determineFetchGranularity,
  filterByGranularity,
  GranularityLevel,
  RawTraceEvent,
  STEP_KEYS,
  STEP_TITLES,
} from './debug/utils';
import TraceTable from './trace/TraceTable';
import TraceBadges from './trace/TraceBadges';
import {
  buildTraceRows,
  collectStepSnapshots,
  groupRowsByStep,
  TraceRowData,
  TraceSection,
  StepSnapshotMap,
} from './trace/TraceTypes';

interface SignalSummary {
  date?: { confirmed?: boolean; value?: string | null };
  room_status?: string | null;
  hash_status?: string | null;
  offer_status?: string | null;
  wait_state?: string | null;
}

interface TraceSummary {
  current_step_major?: number;
  wait_state?: string | null;
  hash_status?: string | null;
  hash_help?: string | null;
}

interface TraceResponse {
  thread_id: string;
  state: Record<string, unknown>;
  confirmed?: SignalSummary;
  summary?: TraceSummary;
  trace: RawTraceEvent[];
}

interface DebugPanelProps {
  threadId: string | null;
  pollMs?: number;
  initialManagerView?: boolean;
}

interface InspectModalProps {
  row: TraceRowData;
  onClose: () => void;
}

function InspectModal({ row, onClose }: InspectModalProps) {
  const payload = row.raw.payload ?? row.raw.data ?? {};
  return (
    <div className="prompt-modal__backdrop" onClick={onClose} role="presentation">
      <div className="prompt-modal" onClick={(event) => event.stopPropagation()} role="dialog">
        <header className="prompt-modal__header">
          <div>
            <h2>Event payload</h2>
            <p className="prompt-modal__meta">{row.event} · {row.functionName} · {row.entity}</p>
          </div>
          <button type="button" onClick={onClose} className="prompt-modal__close">
            ×
          </button>
        </header>
        <pre className="prompt-modal__content">{JSON.stringify(payload, null, 2)}</pre>
      </div>
    </div>
  );
}

function createCsv(rows: TraceRowData[]): string {
  const header = ['Time', 'Step', 'Entity', 'Actor', 'Event', 'Details', 'Value', 'Gate', 'I/O', 'Wait', 'Prompt'];
  const lines = rows.map((row) => {
    const gate = row.gate ? `${row.gate.met}/${row.gate.required}` : '';
    const io = row.io && (row.io.direction || row.io.op)
      ? `${row.io.direction ? row.io.direction.toUpperCase() : ''} ${row.io.op || ''}`.trim() + (row.io.result ? ` → ${row.io.result}` : '')
      : '';
    const value = row.valueItems.map((item) => item.label).join(' | ');
    const functionDetail = row.functionPath || row.functionName || '';
    const argsSummary = row.functionArgs?.length
      ? ` (${row.functionArgs.map((item) => `${item.key}=${item.value}`).join('; ')})`
      : '';
    const promptPieces = [] as string[];
    if (row.prompt?.instruction) {
      promptPieces.push(`Instruction: ${row.prompt.instruction}`);
    }
    if (row.prompt?.reply) {
      promptPieces.push(`Reply: ${row.prompt.reply}`);
    }
    const cells = [
      row.timeLabel,
      row.stepLabel,
      row.entity,
      row.actor,
      row.event,
      `${functionDetail}${argsSummary}`.trim(),
      value,
      gate,
      io,
      row.wait ?? '',
      promptPieces.join(' || '),
    ];
    return cells.map((cell) => `"${(cell ?? '').replace(/"/g, '""')}"`).join(',');
  });
  return [header.join(','), ...lines].join('\n');
}

export default function DebugPanel({ threadId, pollMs = 1500, initialManagerView = false }: DebugPanelProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [granularity, setGranularity] = useState<GranularityLevel>(() => {
    if (typeof window === 'undefined') {
      return 'logic';
    }
    const stored = window.localStorage.getItem('debugLevel');
    if (stored === 'manager' || stored === 'logic' || stored === 'full') {
      return stored as GranularityLevel;
    }
    return 'logic';
  });
  const [showManagerView, setShowManagerView] = useState(initialManagerView);
  const [rawEvents, setRawEvents] = useState<RawTraceEvent[]>([]);
  const [stateSnapshot, setStateSnapshot] = useState<Record<string, unknown>>({});
  const [signals, setSignals] = useState<SignalSummary | undefined>();
  const [summary, setSummary] = useState<TraceSummary | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [inspectRow, setInspectRow] = useState<TraceRowData | null>(null);
  const [managerLines, setManagerLines] = useState<string[]>([]);

  const tableScrollerRef = useRef<HTMLDivElement | null>(null);
  const bufferRef = useRef<ReturnType<typeof createBufferFlusher<RawTraceEvent[]>> | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem('debugLevel', granularity);
  }, [granularity]);

  useEffect(() => {
    bufferRef.current = createBufferFlusher<RawTraceEvent[]>({ onFlush: (items) => setRawEvents(items) });
    return () => bufferRef.current?.dispose();
  }, []);

  useEffect(() => {
    bufferRef.current?.setPaused(paused);
  }, [paused]);

  useEffect(() => {
    if (!threadId) {
      setRawEvents([]);
      setStateSnapshot({});
      setError('Waiting for session to start…');
      setDisabled(false);
      return;
    }

    const controller = new AbortController();

    const fetchTrace = async () => {
      try {
        const query = new URLSearchParams();
        query.set('granularity', determineFetchGranularity(granularity));
        const response = await fetch(`/api/debug/threads/${encodeURIComponent(threadId)}?${query.toString()}`, {
          signal: controller.signal,
        });
        if (response.status === 404) {
          setDisabled(true);
          setError('Tracing disabled. Ensure DEBUG_TRACE is unset or set to 1, then restart the server.');
          return;
        }
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = (await response.json()) as TraceResponse;
        setStateSnapshot(payload.state || {});
        setSignals(payload.confirmed);
        setSummary(payload.summary);
        bufferRef.current?.push(payload.trace ?? []);
        setError(null);
        setDisabled(false);
      } catch (err) {
        if ((err as Error).name === 'AbortError') {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load trace');
      }
    };

    fetchTrace();
    const timer = window.setInterval(fetchTrace, pollMs);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [threadId, pollMs, granularity]);

  const stepProgress = useMemo(
    () => computeStepProgress({ state: stateSnapshot, summary: signals }),
    [stateSnapshot, signals],
  );

  const currentStepTitle = useMemo(() => {
    const major = summary?.current_step_major;
    if (major && major >= 1 && major <= STEP_KEYS.length) {
      const key = STEP_KEYS[major - 1];
      const recentEvent = [...rawEvents].reverse().find((event) => event.step_major === major);
      const minor = typeof recentEvent?.step_minor === 'number' ? recentEvent.step_minor : null;
      const subStep = minor ? ` · ${major}.${minor}` : '';
      return `Step ${major} · ${STEP_TITLES[key]}${subStep}`;
    }
    return '—';
  }, [rawEvents, summary?.current_step_major]);

  const hilOpen = Boolean((summary && summary.hil_open) ?? stateSnapshot.hil_open ?? false);
  const waitStateRaw = summary?.wait_state ?? signals?.wait_state ?? stateSnapshot.thread_state ?? '—';
  const waitStateLabel = waitStateRaw === 'Waiting on HIL' && !hilOpen ? 'Awaiting Client' : (waitStateRaw || '—');

  const filteredEvents = useMemo(
    () => filterByGranularity(rawEvents, granularity),
    [rawEvents, granularity],
  );

  const traceRows = useMemo(() => buildTraceRows(filteredEvents), [filteredEvents]);

  const stepSnapshots: StepSnapshotMap = useMemo(() => collectStepSnapshots(rawEvents), [rawEvents]);

  const groupedRows = useMemo(() => groupRowsByStep(traceRows), [traceRows]);

  const sections: TraceSection[] = useMemo(() => {
    const result: TraceSection[] = [];
    STEP_KEYS.forEach((stepKey, index) => {
      const major = index + 1;
      const rowsForStep = groupedRows.get(major) ?? [];
      const title = `Step ${major} · ${STEP_TITLES[stepKey]}`;
      const snapshot = stepSnapshots.get(major);
      let progress = stepProgress[stepKey];
      const infoChips: string[] = [];
      if (snapshot) {
        if (major === 1) {
          const intentDetected = Boolean(snapshot.flags.intentDetected);
          const participants = Boolean(snapshot.flags.participants);
          progress = {
            completed: Number(intentDetected) + Number(participants),
            total: 2,
            breakdown: [
              { label: 'Intent detected', met: intentDetected },
              { label: 'Participants captured', met: participants },
            ],
          };
          if (snapshot.flags.emailConfirmed) {
            infoChips.push('Contact email');
          }
        } else if (major === 2) {
          const dateCaptured = Boolean(snapshot.flags.dateCaptured);
          const dateConfirmed = Boolean(snapshot.flags.dateConfirmed);
          progress = {
            completed: Number(dateCaptured) + Number(dateConfirmed),
            total: 2,
            breakdown: [
              { label: 'Date captured', met: dateCaptured },
              { label: 'Date confirmed', met: dateConfirmed },
            ],
          };
        }
      }
      if (rowsForStep.length) {
        result.push({
          key: `step-${major}`,
          stepMajor: major,
          title,
          rows: rowsForStep,
          gateProgress: progress,
          infoChips: infoChips.length ? infoChips : undefined,
        });
      }
    });
    const globalRows = groupedRows.get('global');
    if (globalRows && globalRows.length) {
      result.push({ key: 'global', stepMajor: null, title: 'Global Events', rows: globalRows });
    }
    return result;
  }, [groupedRows, stepProgress, stepSnapshots]);

  useEffect(() => {
    const lines = buildManagerTimeline(filteredEvents, stepProgress);
    setManagerLines(lines);
  }, [filteredEvents, stepProgress]);

  const capturedEntities = useMemo(() => {
    const captured = new Map<string, string>();
    const confirmed = new Map<string, string>();
    traceRows.forEach((row) => {
      row.valueItems.forEach((item) => {
        if (item.kind !== 'chip') {
          return;
        }
        if (item.tone === 'confirmed') {
          confirmed.set(item.label, item.label);
          captured.delete(item.label);
        } else if (item.tone === 'captured') {
          if (!confirmed.has(item.label)) {
            captured.set(item.label, item.label);
          }
        }
      });
    });
    return {
      captured: Array.from(captured.values()),
      confirmed: Array.from(confirmed.values()),
    };
  }, [traceRows]);

  useEffect(() => {
    if (!autoScroll || paused) {
      return;
    }
    if (tableScrollerRef.current) {
      tableScrollerRef.current.scrollTop = tableScrollerRef.current.scrollHeight;
    }
  }, [traceRows.length, autoScroll, paused]);

  const handleInspect = useCallback((row: TraceRowData) => {
    setInspectRow(row);
  }, []);

  const handleRegisterScroller = useCallback((node: HTMLDivElement | null) => {
    tableScrollerRef.current = node;
  }, []);

  const handleCopyTimeline = useCallback(async (lines: string[]) => {
    if (!lines.length) return;
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
    } catch (err) {
      console.warn('Copy failed', err);
    }
  }, []);

  const downloadFile = useCallback((filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, []);

  const handleDownloadCsv = useCallback(() => {
    const csv = createCsv(traceRows);
    downloadFile('debug_timeline.csv', csv);
  }, [downloadFile, traceRows]);

  const downloadReadableLocal = useCallback(() => {
    if (!managerLines.length) return;
    downloadFile('debug_timeline.txt', managerLines.join('\n'));
  }, [downloadFile, managerLines]);

  const handleDownloadJson = useCallback(() => {
    if (!threadId) return;
    const params = new URLSearchParams();
    params.set('granularity', determineFetchGranularity(granularity));
    window.open(`/api/debug/threads/${encodeURIComponent(threadId)}/timeline/download?${params.toString()}`, '_blank');
  }, [threadId, granularity]);

  const downloadReadableServer = useCallback(() => {
    if (!threadId) return;
    const params = new URLSearchParams();
    params.set('granularity', determineFetchGranularity(granularity));
    window.open(`/api/debug/threads/${encodeURIComponent(threadId)}/timeline/text?${params.toString()}`, '_blank');
  }, [threadId, granularity]);

  const badgeData = useMemo(() => {
    const dateConfirmed = Boolean(signals?.date?.confirmed);
    const dateValue = signals?.date?.value;
    const dateLabel = dateConfirmed
      ? dateValue
        ? `Confirmed (${dateValue})`
        : 'Confirmed'
      : 'Pending';
    const roomRaw = (signals?.room_status || '').toString().toLowerCase();
    let roomLabel = 'Not checked';
    let roomTone: 'ok' | 'pending' | 'warn' = 'pending';
    if (roomRaw.includes('available')) {
      roomLabel = 'Available';
      roomTone = 'ok';
    } else if (roomRaw.includes('option') || roomRaw.includes('lock')) {
      roomLabel = 'Option';
      roomTone = 'ok';
    } else if (roomRaw.includes('unavailable') || roomRaw.includes('closed')) {
      roomLabel = 'Unavailable';
      roomTone = 'warn';
    }

    const hashRaw = (summary?.hash_status || signals?.hash_status || 'Unknown').toString();
    const hashLabel = hashRaw || 'Unknown';
    const hashTone: 'ok' | 'pending' | 'warn' = hashLabel.toLowerCase() === 'match'
      ? 'ok'
      : hashLabel.toLowerCase() === 'mismatch'
        ? 'warn'
        : 'pending';

    const offerRaw = (signals?.offer_status || stateSnapshot.offer_status || 'Draft').toString();
    let normalizedOffer = offerRaw.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
    if (!normalizedOffer) {
      normalizedOffer = 'Draft';
    }
    const offerLower = normalizedOffer.toLowerCase();
    if (offerLower.includes('waiting on hil') && !hilOpen) {
      normalizedOffer = 'Draft';
    }
    const displayedOffer = hilOpen && normalizedOffer.toLowerCase() !== 'sent' ? 'Waiting on HIL' : normalizedOffer;
    let offerTone: 'ok' | 'pending' | 'warn' = 'pending';
    if (displayedOffer.toLowerCase() === 'sent') {
      offerTone = 'ok';
    } else if (displayedOffer.toLowerCase() === 'waiting on hil') {
      offerTone = 'warn';
    }

    return [
      {
        id: 'date',
        label: 'Date Confirmation',
        value: dateLabel,
        tone: dateConfirmed ? 'ok' : 'pending',
        description: 'Chosen date status for this thread.',
      },
      {
        id: 'room',
        label: 'Room Status',
        value: roomLabel,
        tone: roomTone,
        description: 'Best evaluated status for selected requirements/date.',
      },
      {
        id: 'hash',
        label: 'Requirements Hash',
        value: hashLabel,
        tone: hashTone,
        description: 'Compares current requirements to last evaluated room hash to decide if re-evaluation is needed.',
      },
      {
        id: 'offer',
        label: 'Offer Status',
        value: displayedOffer,
        tone: offerTone,
        description: 'Offer composition and delivery state.',
      },
    ];
  }, [signals, stateSnapshot.offer_status, summary?.hash_status, hilOpen]);

  return (
    <div className="debug-panel">
      <div className="debug-panel__header">
        <div className="debug-panel__thread">Thread: {threadId || '—'}</div>
        <div className="debug-panel__meta">
          <span>Current Step: {currentStepTitle}</span>
          <span>Wait State: {waitStateLabel}</span>
        </div>
      </div>

      <TraceBadges badges={badgeData} />

      <Toolbar
        autoScroll={autoScroll}
        paused={paused}
        onToggleAutoScroll={() => setAutoScroll((prev) => !prev)}
        onTogglePaused={() => setPaused((prev) => !prev)}
        granularity={granularity}
        onGranularityChange={(value) => setGranularity(value)}
        onDownloadJson={handleDownloadJson}
        onDownloadCsv={handleDownloadCsv}
        onDownloadReadable={downloadReadableServer}
        showManagerView={showManagerView}
        onToggleManagerView={() => setShowManagerView((prev) => !prev)}
      />

      {disabled && error && <div className="trace-alert trace-alert--warning">{error}</div>}
      {!disabled && error && <div className="trace-alert trace-alert--error">{error}</div>}

      <div className="debug-panel__content">
        <div className="debug-panel__timeline">
          {traceRows.length === 0 ? (
            <div className="trace-alert trace-alert--info">No trace events yet.</div>
          ) : (
            <TraceTable
              sections={sections}
              onInspect={handleInspect}
              hilOpen={hilOpen}
              granularity={granularity}
              onRegisterScroller={handleRegisterScroller}
            />
          )}
        </div>
        <aside className="debug-panel__aside">
          <div className="trace-card">
            <div className="trace-card__title">Tracked Client Information</div>
            <div className="trace-entities">
              <div>
                <div className="trace-entities__label">Captured</div>
                {capturedEntities.captured.length === 0 ? <div className="trace-entities__empty">None</div> : capturedEntities.captured.map((caption, index) => (
                  <span key={`captured-${index}`} className="entity-chip entity-chip--captured">{caption}</span>
                ))}
              </div>
              <div>
                <div className="trace-entities__label">Confirmed</div>
                {capturedEntities.confirmed.length === 0 ? <div className="trace-entities__empty">None</div> : capturedEntities.confirmed.map((caption, index) => (
                  <span key={`confirmed-${index}`} className="entity-chip entity-chip--confirmed">{caption}</span>
                ))}
              </div>
            </div>
          </div>
          {showManagerView && (
            <ManagerView
              lines={managerLines}
              onCopy={handleCopyTimeline}
              onDownload={downloadReadableLocal}
            />
          )}
        </aside>
      </div>

      {inspectRow && <InspectModal row={inspectRow} onClose={() => setInspectRow(null)} />}
    </div>
  );
}

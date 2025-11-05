'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import Toolbar from './debug/Toolbar';
import ManagerView from './debug/ManagerView';
import StateViewer from './debug/StateViewer';
import SubloopLegend from './debug/SubloopLegend';
import { copyTextWithFallback } from './debug/copy';
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
import { resolveOfferStatusChip } from './status/Chips';

interface SignalSummary {
  date?: { confirmed?: boolean; value?: string | null };
  room_status?: string | null;
  room_status_display?: string | null;
  room_selected?: boolean;
  hash_status?: string | null;
  requirements_match?: boolean;
  requirements_match_tooltip?: string | null;
  offer_status?: string | null;
  offer_status_display?: string | null;
  wait_state?: string | null;
  tracked_info?: Record<string, unknown> | null;
}

interface TraceSummary {
  current_step_major?: number;
  wait_state?: string | null;
  hash_status?: string | null;
  hash_help?: string | null;
  requirements_match?: boolean;
  requirements_match_tooltip?: string | null;
  offer_status_display?: string | null;
  room_selected?: boolean;
  tracked_info?: Record<string, unknown> | null;
}

interface TraceResponse {
  thread_id: string;
  state: Record<string, unknown>;
  confirmed?: SignalSummary;
  summary?: TraceSummary;
  trace: RawTraceEvent[];
  time_travel?: { enabled: boolean; as_of_ts?: number | null };
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
      ? ` (${row.functionArgs.map((item) => `${item.key}=${item.fullValue}`).join('; ')})`
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
  const [granularity, setGranularity] = useState<GranularityLevel>('logic');
  const [showManagerView, setShowManagerView] = useState(initialManagerView);
  const [rawEvents, setRawEvents] = useState<RawTraceEvent[]>([]);
  const [stateSnapshot, setStateSnapshot] = useState<Record<string, unknown>>({});
  const [liveState, setLiveState] = useState<Record<string, unknown>>({});
  const [signals, setSignals] = useState<SignalSummary | undefined>();
  const [liveSignals, setLiveSignals] = useState<SignalSummary | undefined>();
  const [summary, setSummary] = useState<TraceSummary | undefined>();
  const [liveSummary, setLiveSummary] = useState<TraceSummary | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [inspectRow, setInspectRow] = useState<TraceRowData | null>(null);
  const [managerLines, setManagerLines] = useState<string[]>([]);
  const [reportCopyState, setReportCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const [timeTravelTs, setTimeTravelTs] = useState<number | null>(null);
  const [timeTravelMeta, setTimeTravelMeta] = useState<{ ts: number; label?: string; event?: string } | null>(null);
  const [timeTravelLoading, setTimeTravelLoading] = useState(false);
  const [timeTravelError, setTimeTravelError] = useState<string | null>(null);
  const [managerToast, setManagerToast] = useState<{ tone: 'ok' | 'error'; message: string } | null>(null);

  const tableScrollerRef = useRef<HTMLDivElement | null>(null);
  const bufferRef = useRef<ReturnType<typeof createBufferFlusher<RawTraceEvent[]>> | null>(null);
  const timeTravelFrameRef = useRef<number | null>(null);
  const scrollMemoryRef = useRef<{ top: number; rowCount: number }>({ top: 0, rowCount: 0 });
  const scrollListenerRef = useRef<((event: Event) => void) | null>(null);
  const traceRowCountRef = useRef<number>(0);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const stored = window.localStorage.getItem('debugLevel');
    if (stored === 'manager' || stored === 'logic' || stored === 'full') {
      setGranularity(stored as GranularityLevel);
    }
  }, []);

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

  useEffect(
    () => () => {
      if (timeTravelFrameRef.current !== null) {
        cancelAnimationFrame(timeTravelFrameRef.current);
      }
      const node = tableScrollerRef.current;
      if (node && scrollListenerRef.current) {
        node.removeEventListener('scroll', scrollListenerRef.current);
        scrollListenerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    bufferRef.current?.setPaused(paused);
  }, [paused]);

  useEffect(() => {
    if (!threadId) {
      setRawEvents([]);
      setStateSnapshot({});
      setLiveState({});
      setLiveSignals(undefined);
      setLiveSummary(undefined);
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
        const nextState = payload.state || {};
        const nextSignals = payload.confirmed;
        const nextSummary = payload.summary;
        setLiveState(nextState);
        setLiveSignals(nextSignals);
        setLiveSummary(nextSummary);
        if (timeTravelTs === null) {
          setStateSnapshot(nextState);
          setSignals(nextSignals);
          setSummary(nextSummary);
        }
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
  }, [threadId, pollMs, granularity, timeTravelTs]);

  useEffect(() => {
    if (timeTravelTs === null) {
      setTimeTravelLoading(false);
      setTimeTravelError(null);
      setTimeTravelMeta(null);
      if (Object.keys(liveState).length) {
        setStateSnapshot(liveState);
      }
      setSignals(liveSignals);
      setSummary(liveSummary);
      return;
    }
    if (!threadId) {
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    const fetchHistorical = async () => {
      setTimeTravelLoading(true);
      setTimeTravelError(null);
      try {
        const query = new URLSearchParams();
        query.set('granularity', determineFetchGranularity(granularity));
        query.set('as_of_ts', String(timeTravelTs));
        const response = await fetch(`/api/debug/threads/${encodeURIComponent(threadId)}?${query.toString()}`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(await response.text() || 'Failed to load point-in-time state');
        }
        const payload = (await response.json()) as TraceResponse;
        if (cancelled) {
          return;
        }
        setStateSnapshot(payload.state || {});
        setSignals(payload.confirmed);
        setSummary(payload.summary);
        if (payload.time_travel?.as_of_ts !== undefined) {
          setTimeTravelMeta((prev) => {
            if (prev) {
              return { ...prev, ts: payload.time_travel!.as_of_ts };
            }
            return { ts: payload.time_travel.as_of_ts };
          });
        }
        setTimeTravelLoading(false);
        setTimeTravelError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') {
          return;
        }
        setTimeTravelLoading(false);
        setTimeTravelError(err instanceof Error ? err.message : 'Unable to load snapshot.');
      }
    };
    fetchHistorical();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [timeTravelTs, threadId, granularity, liveState, liveSignals, liveSummary]);

  const stepProgress = useMemo(
    () => computeStepProgress({ state: stateSnapshot, summary: signals }),
    [stateSnapshot, signals],
  );

  const hasBackendCounters = useMemo(
    () => Boolean(stateSnapshot && typeof stateSnapshot === 'object' && 'step_counters' in stateSnapshot),
    [stateSnapshot],
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
  const currentStepMajor = summary?.current_step_major ?? null;
  const timeTravelActive = timeTravelTs !== null;
  const timeTravelStepMajor = timeTravelActive ? currentStepMajor : null;

  const filteredEvents = useMemo(
    () => filterByGranularity(rawEvents, granularity),
    [rawEvents, granularity],
  );

  const traceRows = useMemo(() => buildTraceRows(filteredEvents), [filteredEvents]);

  useEffect(() => {
    traceRowCountRef.current = traceRows.length;
  }, [traceRows.length]);

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
      const dimmed = timeTravelActive && timeTravelStepMajor !== null && major > timeTravelStepMajor;
      if (snapshot && !hasBackendCounters) {
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
          dimmed,
        });
      }
    });
    const globalRows = groupedRows.get('global');
    if (globalRows && globalRows.length) {
      result.push({ key: 'global', stepMajor: null, title: 'Global Events', rows: globalRows, dimmed: false });
    }
    return result;
  }, [groupedRows, stepProgress, stepSnapshots, hasBackendCounters, timeTravelActive, timeTravelStepMajor]);

  useEffect(() => {
    const lines = buildManagerTimeline(filteredEvents, stepProgress);
    setManagerLines(lines);
  }, [filteredEvents, stepProgress]);

  useEffect(() => {
    setReportCopyState('idle');
  }, [threadId]);

  useEffect(() => {
    if (reportCopyState === 'idle') {
      return;
    }
    const timer = window.setTimeout(() => setReportCopyState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [reportCopyState]);

  useEffect(() => {
    if (!managerToast) {
      return;
    }
    const timer = window.setTimeout(() => setManagerToast(null), 2000);
    return () => window.clearTimeout(timer);
  }, [managerToast]);

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
    const trackedInfo =
      (signals?.tracked_info ??
        summary?.tracked_info ??
        (stateSnapshot && typeof stateSnapshot === 'object' ? (stateSnapshot as Record<string, unknown>)['tracked_info'] : null)) as
        | Record<string, unknown>
        | null
        | undefined;

    if (trackedInfo && typeof trackedInfo === 'object') {
      const capturedRaw = trackedInfo['billing_address_captured_raw'];
      const savedFlag = trackedInfo['billing_address_saved'];
      const billingCaptured = typeof capturedRaw === 'string' && capturedRaw.trim().length > 0;
      const billingSaved = savedFlag === true;
      if (billingCaptured) {
        captured.set('billing (captured)', 'billing (captured)');
      }
      if (billingSaved) {
        confirmed.set('Billing saved', 'Billing saved');
        captured.delete('billing (captured)');
      }
    }
    return {
      captured: Array.from(captured.values()),
      confirmed: Array.from(confirmed.values()),
    };
  }, [traceRows, signals, summary, stateSnapshot]);

  useEffect(() => {
    if (!autoScroll || paused) {
      return;
    }
    if (tableScrollerRef.current) {
      tableScrollerRef.current.scrollTop = tableScrollerRef.current.scrollHeight;
    }
  }, [traceRows.length, autoScroll, paused]);

  useLayoutEffect(() => {
    const node = tableScrollerRef.current;
    if (!node) {
      return;
    }
    const memory = scrollMemoryRef.current;
    if (memory.rowCount === traceRows.length) {
      node.scrollTop = memory.top;
    }
  }, [traceRows.length, paused]);

  const handleInspect = useCallback((row: TraceRowData) => {
    setInspectRow(row);
  }, []);

  const handleTimeTravel = useCallback((row: TraceRowData) => {
    if (!row) {
      return;
    }
    const schedule = () => {
      const rawEvent = typeof row.raw.event === 'string' ? row.raw.event : undefined;
      const rawSubject = typeof row.raw.subject === 'string' ? row.raw.subject : undefined;
      const rawDetails = typeof row.raw.details === 'string' ? row.raw.details : undefined;
      setTimeTravelMeta({
        ts: row.timestamp,
        label: row.timeLabel,
        event: row.event || rawEvent || rawSubject || rawDetails || undefined,
      });
      setTimeTravelTs(row.timestamp);
      setPaused(true);
    };
    if (timeTravelFrameRef.current !== null) {
      cancelAnimationFrame(timeTravelFrameRef.current);
    }
    timeTravelFrameRef.current = requestAnimationFrame(() => {
      schedule();
      timeTravelFrameRef.current = null;
    });
  }, []);

  const handleExitTimeTravel = useCallback(() => {
    setTimeTravelTs(null);
    setTimeTravelMeta(null);
    setTimeTravelError(null);
  }, []);

  const handleRegisterScroller = useCallback((node: HTMLDivElement | null) => {
    const previous = tableScrollerRef.current;
    if (previous && scrollListenerRef.current) {
      previous.removeEventListener('scroll', scrollListenerRef.current);
      scrollListenerRef.current = null;
    }
    tableScrollerRef.current = node;
    if (node) {
      const handler = () => {
        scrollMemoryRef.current = {
          top: node.scrollTop,
          rowCount: traceRowCountRef.current,
        };
      };
      node.addEventListener('scroll', handler);
      scrollListenerRef.current = handler;
      scrollMemoryRef.current = {
        top: node.scrollTop,
        rowCount: traceRowCountRef.current,
      };
    }
  }, []);

  const handleCopyTimeline = useCallback(async (lines: string[]) => {
    if (!lines.length) {
      return;
    }
    const text = lines.join('\n');

    try {
      await copyTextWithFallback(text);
      setManagerToast({ tone: 'ok', message: 'Copied' });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Copy failed';
      console.warn('Copy failed', err);
      setManagerToast({ tone: 'error', message });
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

  const handleCopyReport = useCallback(async () => {
    if (!threadId) {
      return;
    }
    try {
      const params = new URLSearchParams();
      params.set('granularity', determineFetchGranularity(granularity));
      params.set('persist', '1');
      const response = await fetch(`/api/debug/threads/${encodeURIComponent(threadId)}/report?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`Report request failed with status ${response.status}`);
      }
      const text = await response.text();
      await navigator.clipboard.writeText(text);
      setReportCopyState('copied');
    } catch (err) {
      console.warn('Copy report failed', err);
      setReportCopyState('error');
    }
  }, [threadId, granularity]);

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

    const roomStatusDisplay = (signals?.room_status_display
      ?? summary?.room_status_display
      ?? signals?.room_status
      ?? 'Unselected').toString().trim();
    const roomLabel = roomStatusDisplay || 'Unselected';
    const roomRaw = roomLabel.toLowerCase();
    let roomTone: 'ok' | 'pending' | 'warn' | 'info' | 'success' | 'muted' = 'pending';
    if (roomRaw.includes('available') || roomRaw.includes('option') || roomRaw.includes('locked')) {
      roomTone = 'ok';
    } else if (roomRaw.includes('unavailable') || roomRaw.includes('hold') || roomRaw.includes('closed')) {
      roomTone = 'warn';
    } else if (roomRaw.includes('waiting')) {
      roomTone = 'info';
    } else if (roomRaw.includes('unselected') || roomRaw.length === 0) {
      roomTone = 'pending';
    }

    let requirementsStatus: boolean | null = null;
    if (typeof signals?.requirements_match === 'boolean') {
      requirementsStatus = signals.requirements_match;
    } else if (typeof summary?.requirements_match === 'boolean') {
      requirementsStatus = summary.requirements_match ?? null;
    } else {
      const hashText = (summary?.hash_status || signals?.hash_status || '').toString().toLowerCase();
      if (hashText === 'match') {
        requirementsStatus = true;
      } else if (hashText === 'mismatch') {
        requirementsStatus = false;
      }
    }
    const requirementsLabel = requirementsStatus === true
      ? 'Match'
      : requirementsStatus === false
        ? 'Mismatch'
        : 'Unknown';
    const requirementsTone: 'ok' | 'pending' | 'warn' = requirementsStatus === true
      ? 'ok'
      : requirementsStatus === false
        ? 'warn'
        : 'pending';
    const requirementsDescription = signals?.requirements_match_tooltip
      || summary?.requirements_match_tooltip
      || summary?.hash_help
      || 'Deterministic digest of date, pax, and constraints. "Match" means inputs didn’t change since the last evaluation.';

    const snapshotInfo = stateSnapshot && typeof stateSnapshot === 'object'
      ? (stateSnapshot as Record<string, unknown>)
      : undefined;
    const snapshotOfferDisplay = snapshotInfo?.['offer_status_display'];
    const snapshotOfferStatus = snapshotInfo?.['offer_status'];

    const offerChip = resolveOfferStatusChip(
      signals?.offer_status_display
      ?? summary?.offer_status_display
      ?? signals?.offer_status
      ?? (typeof snapshotOfferDisplay === 'string' ? snapshotOfferDisplay : undefined)
      ?? (typeof snapshotOfferStatus === 'string' ? snapshotOfferStatus : undefined)
      ?? '—',
    );
    const offerTone = offerChip.tone;

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
        id: 'requirements',
        label: 'Requirements match',
        value: requirementsLabel,
        tone: requirementsTone,
        description: requirementsDescription,
      },
      {
        id: 'offer',
        label: 'Offer Status',
        value: offerChip.label,
        tone: offerTone,
        description: 'Offer composition and delivery state.',
      },
    ];
  }, [
    signals,
    summary,
    stateSnapshot,
  ]);

  return (
    <div className="debug-panel">
      <div className="debug-panel__header">
        <div className="debug-panel__thread">Thread: {threadId || '—'}</div>
        <div className="debug-panel__header-right">
          <div className="debug-panel__meta">
            <span>Current Step: {currentStepTitle}</span>
            <span>Wait State: {waitStateLabel}</span>
          </div>
          <SubloopLegend />
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
        onCopyReport={threadId ? handleCopyReport : null}
        copyReportDisabled={!threadId}
        copyReportState={reportCopyState}
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
              onTimeTravel={handleTimeTravel}
              hilOpen={hilOpen}
              granularity={granularity}
              onRegisterScroller={handleRegisterScroller}
              timeTravelStepMajor={timeTravelStepMajor}
              activeTimestamp={timeTravelTs}
            />
          )}
        </div>
        <aside className="debug-panel__aside">
          <StateViewer
            state={stateSnapshot}
            isTimeTravel={timeTravelActive}
            loading={timeTravelLoading}
            error={timeTravelError}
            meta={timeTravelMeta}
            onExit={timeTravelActive ? handleExitTimeTravel : undefined}
          />
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
              toast={managerToast}
            />
          )}
        </aside>
      </div>

      {inspectRow && <InspectModal row={inspectRow} onClose={() => setInspectRow(null)} />}
    </div>
  );
}

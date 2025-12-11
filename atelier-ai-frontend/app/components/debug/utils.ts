export const STEP_KEYS = ['Step1_Intake', 'Step2_Date', 'Step3_Room', 'Step4_Offer'] as const;
export type StepKey = (typeof STEP_KEYS)[number];
export const STEP_TITLES: Record<StepKey, string> = {
  Step1_Intake: 'Intake',
  Step2_Date: 'Date Confirmation',
  Step3_Room: 'Room Evaluation',
  Step4_Offer: 'Offer',
};

export type GranularityLevel = 'manager' | 'logic' | 'full';
export type Lane = 'step' | 'gate' | 'db' | 'entity' | 'detour' | 'qa' | 'draft' | string;

export interface RawTraceEvent {
  thread_id: string;
  ts: number;
  seq?: number | null;
  row_id?: string | null;
  kind: string;
  lane: Lane;
  step?: string | null;
  owner_step?: string | null;
  step_major?: number | null;
  step_minor?: number | null;
  entity?: string | null;
  actor?: string | null;
  event?: string | null;
  details?: string | null;
  detail?: string | null;
  subject?: string | null;
  status?: string | null;
  summary?: string | null;
  payload?: Record<string, unknown> | null;
  data?: Record<string, unknown> | null;
  captured_additions?: string[] | null;
  confirmed_now?: string[] | null;
  gate?: {
    met?: number;
    required?: number;
    missing?: string[];
    result?: string;
    label?: string;
  } | null;
  io?: {
    direction?: string;
    op?: string;
    result?: string;
  } | null;
  db?: {
    mode?: string;
    op?: string;
    result?: string;
    duration_ms?: number;
  } | null;
  wait_state?: string | null;
  prompt_preview?: string | null;
  hash_status?: string | null;
  hash_help?: string | null;
  subloop?: string | null;
  requirements_match?: boolean | null;
  requirements_match_tooltip?: string | null;
  offer_status_display?: string | null;
  tracked_info?: Record<string, unknown> | null;
  entity_context?: Record<string, unknown> | null;
  detour?: Record<string, unknown> | null;
  draft?: Record<string, unknown> | null;
  loop?: boolean;
  detour_to_step?: number | null;
  granularity?: string | null;
}

export interface PromptTabPayload {
  prompt?: string;
  toolPayload?: unknown;
  modelChoice?: unknown;
}

export interface GateState {
  met: number;
  required: number;
  missing: string[];
}

export interface IoState {
  direction?: string;
  op?: string;
  result?: string;
}

export interface DisplayRow {
  id: string;
  rowId: string;
  time: number;
  timeLabel: string;
  stepMajor: number | null;
  stepMinor: number | null;
  stepLabel: string;
  stepKey: StepKey | 'Global';
  stepTitle: string;
  entity: string;
  actor: string;
  eventLabel: string;
  details: string;
  capturedChips: string[];
  confirmedChips: string[];
  gate?: GateState;
  io?: IoState;
  waitState?: string;
  promptPreview?: string | null;
  promptTabs?: PromptTabPayload;
  raw: RawTraceEvent;
}

export interface StepGroupDisplay {
  key: StepKey | 'Global';
  stepMajor: number | null;
  title: string;
  rows: DisplayRow[];
}

export interface DisplayData {
  groups: StepGroupDisplay[];
  filteredEvents: RawTraceEvent[];
  flatRows: DisplayRow[];
}

export interface StepProgressItem {
  label: string;
  met: boolean;
  hint?: string;
}

export interface StepCounterSnapshot {
  met: number;
  total: number;
  missing?: string[];
}

export interface StepCounterMap {
  [key: string]: StepCounterSnapshot | undefined;
}

export interface GateProgress {
  completed: number;
  total: number;
  breakdown: StepProgressItem[];
}

export interface StepProgressMap {
  [key: string]: GateProgress;
}

export interface StepSignalsInput {
  state: Record<string, unknown>;
  summary?: {
    date?: { confirmed?: boolean; value?: string | null };
    room_status?: string | null;
    room_status_display?: string | null;
    room_selected?: boolean | null;
    hash_status?: string | null;
    requirements_match?: boolean;
    requirements_match_tooltip?: string | null;
    offer_status?: string | null;
    offer_status_display?: string | null;
  };
}

const MANAGER_ENTITY = new Set(['Trigger', 'Agent', 'Condition', 'Draft', 'HIL']);
const LOGIC_ENTITY_EXTRA = new Set(['Detour', 'DB Action', 'Waiting', 'Q&A']);

export function determineFetchGranularity(level: GranularityLevel): 'logic' | 'verbose' {
  return level === 'full' ? 'verbose' : 'logic';
}

export function filterByGranularity(events: RawTraceEvent[], level: GranularityLevel): RawTraceEvent[] {
  if (level === 'full') {
    return events;
  }

  return events.filter((event) => {
    const entity = event.entity || '';
    if (level === 'manager') {
      if (entity === 'DB Action') {
        return (event.io?.direction || '').toUpperCase() === 'WRITE';
      }
      return MANAGER_ENTITY.has(entity);
    }

    if (MANAGER_ENTITY.has(entity)) {
      return true;
    }
    if (entity === 'DB Action') {
      return true;
    }
    if (LOGIC_ENTITY_EXTRA.has(entity)) {
      return true;
    }
    return false;
  });
}

export function computeStepProgress({ state, summary }: StepSignalsInput): StepProgressMap {
  const result: StepProgressMap = {};

  const counters = (state.step_counters as StepCounterMap | undefined) ?? {};

  const build = (items: StepProgressItem[], counter?: StepCounterSnapshot | null): GateProgress => {
    const fallbackCompleted = items.filter((item) => item.met).length;
    const completed = typeof counter?.met === 'number' ? counter.met : fallbackCompleted;
    const total = typeof counter?.total === 'number' ? counter.total : items.length;
    return {
      completed,
      total,
      breakdown: items,
    };
  };

  const intentPresent = Boolean(state.intent || state.intent_label);
  const participantsPresent = Boolean(
    state.participants ||
    state.number_of_participants ||
    state.participants_captured ||
    (typeof state.event_data === 'object' && state.event_data !== null && (state.event_data as Record<string, unknown>)['Number of Participants'])
  );
  result.Step1_Intake = build([
    { label: 'Intent detected', met: intentPresent },
    { label: 'Participants captured', met: participantsPresent },
  ], counters.Step1_Intake ?? counters.Step1_intake ?? counters.step1);

  const chosenDate = Boolean(state.chosen_date || state.event_date || state.date);
  const dateConfirmed = Boolean(summary?.date?.confirmed);
  result.Step2_Date = build([
    { label: 'Date captured', met: chosenDate },
    { label: 'Date confirmed', met: dateConfirmed },
  ], counters.Step2_Date ?? counters.Step2_date ?? counters.step2);

  const backendRoomSelected = typeof summary?.room_selected === 'boolean' ? summary.room_selected : undefined;
  const roomSelected = backendRoomSelected ?? false;
  const summaryRequirementsMatch = summary?.requirements_match;
  const requirementsMatch = typeof summaryRequirementsMatch === 'boolean'
    ? summaryRequirementsMatch
    : null;
  const requirementsHint = summary?.requirements_match_tooltip || "Deterministic digest of date, pax, and constraints. 'Match' means inputs didn’t change since the last evaluation.";
  result.Step3_Room = build([
    { label: 'Date confirmed', met: dateConfirmed },
    { label: 'Room selected', met: roomSelected },
    { label: 'Requirements match', met: requirementsMatch === true, hint: requirementsHint },
  ], counters.Step3_Room ?? counters.Step3_room ?? counters.step3);

  const offerDrafted = Boolean(state.current_offer_id || state.offer_body);
  const offerStatusDisplay = (summary?.offer_status_display || summary?.offer_status || '').toLowerCase();
  const offerSent = offerStatusDisplay === 'sent' || offerStatusDisplay === 'confirmed by hil';
  const awaitingHil = offerStatusDisplay === 'waiting on hil';
  result.Step4_Offer = build([
    { label: 'Offer drafted', met: offerDrafted },
    { label: 'Awaiting HIL', met: awaitingHil || offerSent },
    { label: 'Offer sent', met: offerSent },
  ]);

  return result;
}

export function formatTimeLabel(timestamp: number): string {
  try {
    return new Date(timestamp * 1000).toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (error) {
    return timestamp.toFixed(0);
  }
}

function stepKeyFromMajor(stepMajor: number | null): StepKey | 'Global' {
  if (!stepMajor || stepMajor < 1 || stepMajor > STEP_KEYS.length) {
    return 'Global';
  }
  return STEP_KEYS[stepMajor - 1];
}

function stepTitle(stepMajor: number | null): string {
  if (!stepMajor) {
    return 'Global Events';
  }
  const key = stepKeyFromMajor(stepMajor);
  if (key === 'Global') {
    return 'Global Events';
  }
  return `Step ${stepMajor} · ${STEP_TITLES[key]}`;
}

function buildPromptTabs(event: RawTraceEvent): PromptTabPayload | undefined {
  const payload = event.payload || event.data;
  const draftInfo = event.draft || {};
  const footer = (draftInfo as Record<string, unknown>)?.footer;
  const prompt = typeof payload?.prompt === 'string' ? (payload.prompt as string) : undefined;
  const toolPayload = payload && typeof payload === 'object' ? payload : undefined;
  const modelChoice = footer && typeof footer === 'object' ? footer : undefined;
  if (!prompt && !toolPayload && !modelChoice) {
    return undefined;
  }
  return { prompt, toolPayload, modelChoice };
}

function buildDisplayRow(event: RawTraceEvent, index: number): DisplayRow {
  const stepMajor = typeof event.step_major === 'number' ? event.step_major : null;
  const stepMinor = typeof event.step_minor === 'number' ? event.step_minor : null;
  const majorKey = stepKeyFromMajor(stepMajor);
  const title = stepTitle(stepMajor);
  const stepLabel =
    stepMajor && stepMinor ? `${stepMajor}.${stepMinor}` : stepMajor ? `${stepMajor}.—` : '—';
  const entity = event.entity || 'Condition';
  const actor = event.actor || 'System';
  const time = event.ts || 0;
  const id = event.row_id || `${event.thread_id}-${index}-${time}`;
  const eventLabel = event.event || event.kind || 'Event';
  const details =
    event.details ||
    event.summary ||
    event.detail ||
    event.subject ||
    event.kind;
  const capturedChips = Array.isArray(event.captured_additions)
    ? event.captured_additions.filter((chip): chip is string => typeof chip === 'string')
    : [];
  const confirmedChips = Array.isArray(event.confirmed_now)
    ? event.confirmed_now.filter((chip): chip is string => typeof chip === 'string')
    : [];

  let gate: GateState | undefined;
  if (event.gate && typeof event.gate === 'object') {
    const met = typeof event.gate.met === 'number' ? event.gate.met : 0;
    const required = typeof event.gate.required === 'number' ? event.gate.required : 0;
    const missing =
      Array.isArray(event.gate.missing) && event.gate.missing.length
        ? event.gate.missing.map((item) => String(item))
        : [];
    gate = { met, required, missing };
  }

  let io: IoState | undefined;
  if (event.io && typeof event.io === 'object') {
    io = {
      direction: event.io.direction,
      op: event.io.op,
      result: event.io.result,
    };
  }

  const promptTabs = buildPromptTabs(event);

  return {
    id,
    rowId: id,
    time,
    timeLabel: formatTimeLabel(time),
    stepMajor,
    stepMinor,
    stepLabel,
    stepKey: majorKey,
    stepTitle: title,
    entity,
    actor,
    eventLabel,
    details,
    capturedChips,
    confirmedChips,
    gate,
    io,
    waitState: event.wait_state || undefined,
    promptPreview: event.prompt_preview || undefined,
    promptTabs,
    raw: event,
  };
}

export interface BuildRowsOptions {
  events: RawTraceEvent[];
  level: GranularityLevel;
}

export function buildDisplayData({ events, level }: BuildRowsOptions): DisplayData {
  const filteredByGranularity = filterByGranularity(events, level);
  const groupsMap = new Map<StepKey | 'Global', DisplayRow[]>();
  const flatRows: DisplayRow[] = [];

  filteredByGranularity.forEach((event, index) => {
    const row = buildDisplayRow(event, index);
    flatRows.push(row);
    const key = row.stepKey;
    if (!groupsMap.has(key)) {
      groupsMap.set(key, []);
    }
    groupsMap.get(key)!.push(row);
  });

  const orderedGroups: StepGroupDisplay[] = [];
  STEP_KEYS.forEach((stepKey, idx) => {
    const stepMajor = idx + 1;
    const rows = groupsMap.get(stepKey) || [];
    if (rows.length) {
      rows.sort((a, b) => a.time - b.time);
      orderedGroups.push({
        key: stepKey,
        stepMajor,
        title: stepTitle(stepMajor),
        rows,
      });
    }
  });

  const globalRows = groupsMap.get('Global') || [];
  if (globalRows.length) {
    globalRows.sort((a, b) => a.time - b.time);
    orderedGroups.push({
      key: 'Global',
      stepMajor: null,
      title: 'Global Events',
      rows: globalRows,
    });
  }

  return {
    groups: orderedGroups,
    filteredEvents: filteredByGranularity,
    flatRows,
  };
}

export function buildManagerTimeline(events: RawTraceEvent[], stepProgress: StepProgressMap): string[] {
  if (!events.length) {
    return [];
  }
  return events
    .slice()
    .sort((a, b) => (a.ts || 0) - (b.ts || 0))
    .map((event) => {
      const stepMajor = typeof event.step_major === 'number' ? event.step_major : null;
      const label = stepTitle(stepMajor);
      const progress = stepMajor ? stepProgress[stepKeyFromMajor(stepMajor)] : undefined;
      const progressText =
        progress && progress.total > 0 ? ` (${progress.completed}/${progress.total})` : '';
      const entity = event.entity || 'Event';
      const verb = event.event || event.kind;
      const detail = event.details || event.summary || event.detail || event.subject || '';
      const wait = event.wait_state ? ` → ${event.wait_state}` : '';
      return `[${formatTimeLabel(event.ts || 0)}] ${label}${progressText} → ${entity} ${verb}: ${detail}${wait}`;
    });
}

export function createBufferFlusher<T>(options: { onFlush: (items: T[]) => void }) {
  const buffer: { items: T[] } = { items: [] };
  let raf: number | null = null;
  let paused = false;

  const runtime =
    typeof window !== 'undefined' ? window : ((globalThis as unknown) as Window & typeof globalThis);
  const request =
    typeof runtime.requestAnimationFrame === 'function'
      ? runtime.requestAnimationFrame.bind(runtime)
      : ((cb: FrameRequestCallback) => runtime.setTimeout(cb, 16) as unknown as number);
  const cancel =
    typeof runtime.cancelAnimationFrame === 'function'
      ? runtime.cancelAnimationFrame.bind(runtime)
      : runtime.clearTimeout.bind(runtime);

  const flush = () => {
    if (paused) return;
    raf = null;
    options.onFlush(buffer.items);
  };

  return {
    push(items: T[]) {
      buffer.items = items;
      if (paused) {
        return;
      }
      if (raf !== null) {
        cancel(raf);
      }
      raf = request(flush);
    },
    setPaused(nextPaused: boolean) {
      paused = nextPaused;
      if (!paused && buffer.items.length) {
        if (raf !== null) {
          cancel(raf);
        }
        raf = request(flush);
      }
    },
    dispose() {
      if (raf !== null) {
        cancel(raf);
      }
    },
  };
}

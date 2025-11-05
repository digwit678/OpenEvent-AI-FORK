import { RawTraceEvent, STEP_KEYS, STEP_TITLES, StepKey, formatTimeLabel, GateProgress } from '../debug/utils';

export type TraceEntity =
  | 'TRIGGER'
  | 'AGENT'
  | 'HIL'
  | 'DB_ACTION'
  | 'CONDITION'
  | 'DETOUR'
  | 'Q&A'
  | 'WAITING'
  | 'DRAFT'
  | 'UNKNOWN';

export interface TraceValueChip {
  kind: 'chip';
  label: string;
  tone: 'captured' | 'confirmed' | 'info';
}

export interface TraceValueText {
  kind: 'text';
  label: string;
  muted?: boolean;
}

export type TraceValueItem = TraceValueChip | TraceValueText;

export interface TraceGateInfo {
  met: number;
  required: number;
  missing: string[];
  label?: string;
}

export interface TraceIoInfo {
  direction?: string;
  op?: string;
  result?: string;
}

export interface TracePromptInfo {
  instruction?: string;
  reply?: string;
}

export interface TraceFunctionArg {
  key: string;
  value: string;
  fullValue: string;
}

export interface TraceRowData {
  id: string;
  timestamp: number;
  stepMajor: number | null;
  stepMinor: number | null;
  stepLabel: string;
  stepTitle: string;
  stepKey: StepKey | 'Global';
  entity: TraceEntity;
  rawEntity: string;
  actor: string;
  event: string;
  functionName: string;
  functionPath?: string | null;
  functionArgs: TraceFunctionArg[];
  valueItems: TraceValueItem[];
  gate?: TraceGateInfo;
  io?: TraceIoInfo;
  wait?: string | null;
  timeLabel: string;
  prompt?: TracePromptInfo;
  lane?: string | null;
  raw: RawTraceEvent;
}

export interface StepSnapshotFlags {
  intentDetected?: boolean;
  participants?: boolean;
  emailConfirmed?: boolean;
  dateCaptured?: boolean;
  dateConfirmed?: boolean;
}

export interface StepSnapshot {
  ts: number;
  flags: StepSnapshotFlags;
}

export type StepSnapshotMap = Map<number, StepSnapshot>;

const ENTITY_MAP: Record<string, TraceEntity> = {
  trigger: 'TRIGGER',
  agent: 'AGENT',
  hil: 'HIL',
  'db action': 'DB_ACTION',
  db_action: 'DB_ACTION',
  condition: 'CONDITION',
  detour: 'DETOUR',
  'q&a': 'Q&A',
  waiting: 'WAITING',
  draft: 'DRAFT',
};

function normalizeEntity(entity: string | null | undefined): TraceEntity {
  if (!entity) {
    return 'UNKNOWN';
  }
  const key = entity.trim().toLowerCase();
  return ENTITY_MAP[key] ?? 'UNKNOWN';
}

function deriveStepMajor(event: RawTraceEvent): number | null {
  if (typeof event.step_major === 'number' && !Number.isNaN(event.step_major)) {
    return event.step_major;
  }
  const owner = event.owner_step || event.step;
  if (!owner) {
    return null;
  }
  const match = /step\s*(\d+)/i.exec(owner);
  if (match) {
    const value = parseInt(match[1], 10);
    return Number.isNaN(value) ? null : value;
  }
  return null;
}

function deriveStepMinor(event: RawTraceEvent): number | null {
  if (typeof event.step_minor === 'number' && !Number.isNaN(event.step_minor)) {
    return event.step_minor;
  }
  return null;
}

function deriveStepKey(major: number | null): StepKey | 'Global' {
  if (!major || major < 1 || major > STEP_KEYS.length) {
    return 'Global';
  }
  return STEP_KEYS[major - 1];
}

const MAX_FUNCTION_ARGS = 5;
const MAX_ARG_VALUE_LENGTH = 80;
const PROMPT_ARG_VALUE_LENGTH = 60;
const DETAIL_ARG_KEYS = ['args', 'kwargs', 'inputs', 'parameters', 'params', 'payload'];
const PROMPT_ARG_KEYS = new Set(['prompt_text', 'message_text', 'reply_text']);
const DETAIL_IGNORE_KEYS = new Set(['fn', 'label', 'kind']);

interface TraceFunctionInfo {
  label: string;
  path: string | null;
  args: TraceFunctionArg[];
}

interface FormattedArgValue {
  short: string;
  full: string;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function truncateValue(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  if (maxLength <= 1) {
    return value.slice(0, 1);
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function formatArgValue(key: string, value: unknown): FormattedArgValue | null {
  if (value === undefined) {
    return null;
  }
  if (value === null) {
    return { short: 'null', full: 'null' };
  }
  if (typeof value === 'string') {
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (!normalized.length) {
      return { short: '""', full: '""' };
    }
    const maxLength = PROMPT_ARG_KEYS.has(key) ? PROMPT_ARG_VALUE_LENGTH : MAX_ARG_VALUE_LENGTH;
    return {
      short: truncateValue(normalized, maxLength),
      full: normalized,
    };
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      const text = String(value);
      return { short: text, full: text };
    }
    const formatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3, minimumFractionDigits: 0 });
    return {
      short: formatter.format(value),
      full: String(value),
    };
  }
  if (typeof value === 'boolean') {
    const text = value ? 'true' : 'false';
    return { short: text, full: text };
  }
  try {
    const serialized = JSON.stringify(value);
    if (typeof serialized === 'string' && serialized.length) {
      return {
        short: truncateValue(serialized, MAX_ARG_VALUE_LENGTH),
        full: serialized,
      };
    }
  } catch {
    // fall through to generic handling
  }
  const fallback = String(value);
  return {
    short: truncateValue(fallback, MAX_ARG_VALUE_LENGTH),
    full: fallback,
  };
}

function deriveFunctionArgs(
  event: RawTraceEvent,
  detailObject: Record<string, unknown> | null,
): TraceFunctionArg[] {
  const args: TraceFunctionArg[] = [];
  const seen = new Set<string>();

  const addArg = (key: string, value: unknown) => {
    if (args.length >= MAX_FUNCTION_ARGS) {
      return;
    }
    const formatted = formatArgValue(key, value);
    if (!formatted) {
      return;
    }
    const signature = `${key}:${formatted.short}`;
    if (seen.has(signature)) {
      return;
    }
    seen.add(signature);
    args.push({ key, value: formatted.short, fullValue: formatted.full });
  };

  const processObject = (source: Record<string, unknown> | null | undefined, ignoreKeys?: Set<string>) => {
    if (!source) {
      return;
    }
    for (const [key, value] of Object.entries(source)) {
      if (args.length >= MAX_FUNCTION_ARGS) {
        break;
      }
      if (ignoreKeys?.has(key)) {
        continue;
      }
      addArg(key, value);
    }
  };

  if (detailObject) {
    DETAIL_ARG_KEYS.forEach((candidateKey) => {
      if (args.length >= MAX_FUNCTION_ARGS) {
        return;
      }
      if (!(candidateKey in detailObject)) {
        return;
      }
      const candidate = detailObject[candidateKey];
      if (isPlainObject(candidate)) {
        processObject(candidate as Record<string, unknown>);
      } else {
        addArg(candidateKey, candidate);
      }
    });
    const skipKeys = new Set<string>([...DETAIL_IGNORE_KEYS, ...DETAIL_ARG_KEYS]);
    processObject(detailObject, skipKeys);
  }

  if (isPlainObject(event.payload)) {
    processObject(event.payload as Record<string, unknown>);
  }

  const gateRecord = event.gate as Record<string, unknown> | null | undefined;
  const gateInputs = gateRecord && gateRecord['inputs'];
  if (isPlainObject(gateInputs)) {
    processObject(gateInputs as Record<string, unknown>);
  }

  return args;
}

function deriveFunctionInfo(event: RawTraceEvent): TraceFunctionInfo {
  const detailValue = event.detail as Record<string, unknown> | string | null | undefined;
  const detailObject = (detailValue && typeof detailValue === 'object' && !Array.isArray(detailValue))
    ? (detailValue as Record<string, unknown>)
    : null;

  let label: string | null = null;
  if (detailObject) {
    const detailLabel = detailObject.label;
    if (typeof detailLabel === 'string' && detailLabel.trim()) {
      label = detailLabel.trim();
    }
    if (!label) {
      const fnLabel = detailObject.fn;
      if (typeof fnLabel === 'string' && fnLabel.trim() && !fnLabel.includes('.')) {
        label = fnLabel.trim();
      }
    }
  }
  if (!label && typeof detailValue === 'string' && detailValue.trim()) {
    label = detailValue.trim();
  }
  if (!label && typeof event.details === 'string' && event.details.trim()) {
    label = event.details.trim();
  }
  if (!label && typeof event.summary === 'string' && event.summary.trim()) {
    label = event.summary.trim();
  }
  if (!label && typeof event.subject === 'string' && event.subject.trim()) {
    label = event.subject.trim();
  }
  const fallbackLabel = event.event || event.kind || 'event';
  const resolvedLabel = label || fallbackLabel;

  let path: string | null = null;
  if (detailObject) {
    const explicitPath = detailObject.path;
    if (typeof explicitPath === 'string' && explicitPath.trim()) {
      path = explicitPath.trim();
    }
    if (!path) {
      const fnPath = detailObject.fn;
      if (typeof fnPath === 'string' && fnPath.trim()) {
        path = fnPath.trim();
      }
    }
  }
  if (!path && typeof detailValue === 'string' && detailValue.trim()) {
    path = detailValue.trim();
  }
  if (!path && typeof event.details === 'string' && event.details.trim()) {
    path = event.details.trim();
  }
  if (!path && resolvedLabel.includes('.')) {
    path = resolvedLabel;
  }

  const args = deriveFunctionArgs(event, detailObject);

  return {
    label: resolvedLabel,
    path,
    args,
  };
}

function buildValueItems(event: RawTraceEvent): TraceValueItem[] {
  const items: TraceValueItem[] = [];
  const chipIndex = new Map<string, number>();

  if (Array.isArray(event.captured_additions)) {
    event.captured_additions.forEach((chip) => {
      if (typeof chip === 'string' && chip.trim()) {
        const normalized = chip.trim();
        chipIndex.set(normalized, items.length);
        items.push({ kind: 'chip', label: normalized, tone: 'captured' });
      }
    });
  }

  if (Array.isArray(event.confirmed_now)) {
    event.confirmed_now.forEach((chip) => {
      if (typeof chip === 'string' && chip.trim()) {
        const normalized = chip.trim();
        const existingIndex = chipIndex.get(normalized);
        if (existingIndex !== undefined) {
          items[existingIndex] = { kind: 'chip', label: normalized, tone: 'confirmed' };
        } else {
          chipIndex.set(normalized, items.length);
          items.push({ kind: 'chip', label: normalized, tone: 'confirmed' });
        }
      }
    });
  }

  const payload = (event.payload || event.data) as Record<string, unknown> | undefined;

  if (event.kind === 'AGENT_PROMPT_OUT' && payload && typeof payload === 'object') {
    const outputs = payload.outputs as Record<string, unknown> | undefined;
    if (outputs && typeof outputs === 'object') {
      Object.entries(outputs)
        .slice(0, 4)
        .forEach(([key, value]) => {
          const label = `${key}=${String(value)}`;
          items.push({ kind: 'chip', label, tone: 'info' });
        });
    }
  }

  if (!items.length) {
    if (event.io && typeof event.io.result === 'string' && event.io.result.trim()) {
      items.push({ kind: 'text', label: event.io.result.trim() });
    } else if (typeof event.summary === 'string' && event.summary.trim()) {
      items.push({ kind: 'text', label: event.summary.trim() });
    } else if (typeof event.details === 'string' && event.details.trim()) {
      items.push({ kind: 'text', label: event.details.trim() });
    } else if (payload && typeof payload.summary === 'string' && payload.summary.trim()) {
      items.push({ kind: 'text', label: payload.summary.trim() });
    }
  }

  return items;
}

function extractGate(event: RawTraceEvent): TraceGateInfo | undefined {
  if (!event.gate) {
    return undefined;
  }
  const met = typeof event.gate.met === 'number' ? event.gate.met : 0;
  const required = typeof event.gate.required === 'number' ? event.gate.required : 0;
  const missing = Array.isArray(event.gate.missing)
    ? event.gate.missing.map((item) => String(item))
    : [];
  const label = typeof event.gate.label === 'string' ? event.gate.label : undefined;
  return { met, required, missing, label };
}

function extractIo(event: RawTraceEvent): TraceIoInfo | undefined {
  if (event.io) {
    return {
      direction: event.io.direction,
      op: event.io.op,
      result: event.io.result,
    };
  }
  if (event.db) {
    return {
      direction: event.db.mode,
      op: event.db.op,
      result: event.db.result,
    };
  }
  return undefined;
}

function extractPrompt(event: RawTraceEvent): TracePromptInfo | undefined {
  const payload = (event.payload || event.data) as Record<string, unknown> | undefined;
  if (!payload) {
    return undefined;
  }
  if (event.kind === 'AGENT_PROMPT_IN') {
    const promptText = payload.prompt_text;
    if (typeof promptText === 'string' && promptText.trim()) {
      return { instruction: promptText.trim() };
    }
  }
  if (event.kind === 'AGENT_PROMPT_OUT') {
    const messageText = payload.message_text;
    if (typeof messageText === 'string' && messageText.trim()) {
      return { reply: messageText.trim() };
    }
  }
  return undefined;
}

export function buildTraceRows(events: RawTraceEvent[]): TraceRowData[] {
  return events.map((event, index) => {
    const stepMajor = deriveStepMajor(event);
    const stepMinor = deriveStepMinor(event);
    const stepKey = deriveStepKey(stepMajor);
    const stepTitle = stepKey === 'Global' ? 'Global Events' : `Step ${stepMajor} · ${STEP_TITLES[stepKey]}`;
    const stepLabel = stepMajor && stepMinor ? `${stepMajor}.${stepMinor}` : stepMajor ? `${stepMajor}.—` : '—';
    const id = event.row_id || `${event.thread_id}-${index}`;
    const entity = normalizeEntity(event.entity || null);
    const functionInfo = deriveFunctionInfo(event);
    const valueItems = buildValueItems(event);
    const gate = extractGate(event);
    const io = extractIo(event);
    const prompt = extractPrompt(event);
    const timeLabel = formatTimeLabel(event.ts || 0);

    return {
      id,
      timestamp: event.ts || 0,
      stepMajor,
      stepMinor,
      stepLabel,
      stepTitle,
      stepKey,
      entity,
      rawEntity: event.entity || '',
      actor: event.actor || 'System',
      event: event.event || event.kind || 'EVENT',
      functionName: functionInfo.label,
      functionPath: functionInfo.path,
      functionArgs: functionInfo.args,
      valueItems,
      gate,
      io,
      wait: event.wait_state || null,
      timeLabel,
      prompt,
      lane: event.lane,
      raw: event,
    };
  });
}

export function collectStepSnapshots(events: RawTraceEvent[]): StepSnapshotMap {
  const map: StepSnapshotMap = new Map();
  events.forEach((event) => {
    if (event.kind !== 'STATE_SNAPSHOT') {
      return;
    }
    const major = deriveStepMajor(event);
    if (!major) {
      return;
    }
    const payload = (event.payload || event.data) as Record<string, unknown> | undefined;
    const flags = payload && typeof payload.flags === 'object' ? (payload.flags as StepSnapshotFlags) : undefined;
    if (!flags) {
      return;
    }
    const existing = map.get(major);
    if (!existing || (event.ts || 0) >= existing.ts) {
      map.set(major, { ts: event.ts || 0, flags });
    }
  });
  return map;
}

export function groupRowsByStep(rows: TraceRowData[]): Map<number | 'global', TraceRowData[]> {
  const groups = new Map<number | 'global', TraceRowData[]>();
  rows.forEach((row) => {
    const key = row.stepMajor ?? 'global';
    const bucket = groups.get(key) ?? [];
    bucket.push(row);
    groups.set(key, bucket);
  });
  return groups;
}

export type { RawTraceEvent };

export interface TraceSection {
  key: string;
  stepMajor: number | null;
  title: string;
  rows: TraceRowData[];
  gateProgress?: GateProgress;
  infoChips?: string[];
  dimmed?: boolean;
}

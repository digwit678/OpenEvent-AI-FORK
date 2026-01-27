'use client';

import React, { useMemo } from 'react';

interface StateViewerProps {
  state: Record<string, unknown>;
  isTimeTravel: boolean;
  loading: boolean;
  error: string | null;
  meta?: { ts: number; label?: string; event?: string } | null;
  onExit?: () => void;
}

const EXCLUDED_KEYS = new Set(['__time_travel']);

type UnknownValue = {
  __unknown__?: boolean;
  __value__?: unknown;
};

function isUnknownValue(value: unknown): value is UnknownValue {
  return Boolean(value && typeof value === 'object' && '__unknown__' in (value as Record<string, unknown>));
}

function formatPrimitive(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch (err) {
    return String(value);
  }
}

interface StateTreeProps {
  data: unknown;
  path: string;
}

function StateTree({ data, path }: StateTreeProps): React.ReactElement {
  if (Array.isArray(data)) {
    if (data.length === 0) {
      return <span className="state-tree__value state-tree__value--empty">[]</span>;
    }
    return (
      <ul className="state-tree state-tree__list">
        {data.map((item, index) => (
          <li key={`${path}[${index}]`} className="state-tree__item">
            <span className="state-tree__key state-tree__key--index">[{index}]</span>
            <StateTree data={item} path={`${path}[${index}]`} />
          </li>
        ))}
      </ul>
    );
  }

  if (isUnknownValue(data)) {
    const hint = data.__value__ !== undefined ? formatPrimitive(data.__value__) : null;
    return (
      <span className="state-tree__value state-tree__value--unknown">
        Unknown{hint ? <span className="state-tree__hint"> ({hint})</span> : null}
      </span>
    );
  }

  if (data && typeof data === 'object') {
    const entries = Object.entries(data as Record<string, unknown>).filter(([key]) => !EXCLUDED_KEYS.has(key));
    if (!entries.length) {
      return <span className="state-tree__value state-tree__value--empty">&#123;&#125;</span>;
    }
    return (
      <ul className="state-tree">
        {entries.map(([key, value]) => (
          <li key={`${path}.${key}`} className="state-tree__item">
            <span className="state-tree__key">{key}</span>
            <StateTree data={value} path={`${path}.${key}`} />
          </li>
        ))}
      </ul>
    );
  }

  return <span className="state-tree__value">{formatPrimitive(data)}</span>;
}

export default function StateViewer({ state, isTimeTravel, loading, error, meta, onExit }: StateViewerProps) {
  const visibleKeys = useMemo(
    () => Object.keys(state || {}).filter((key) => !EXCLUDED_KEYS.has(key)),
    [state],
  );
  const label = useMemo(() => {
    if (!isTimeTravel) {
      return 'Live state snapshot';
    }
    if (meta?.label) {
      return `Viewing state at ${meta.label}`;
    }
    if (meta?.ts) {
      const date = new Date(meta.ts * 1000);
      return `Viewing state at ${date.toLocaleTimeString()}`;
    }
    return 'Viewing historical state';
  }, [isTimeTravel, meta?.label, meta?.ts]);

  const eventLabel = meta?.event;

  return (
    <div className="trace-card">
      <div className="trace-card__title">State Snapshot</div>
      <div className={`state-viewer__banner${isTimeTravel ? ' state-viewer__banner--historic' : ' state-viewer__banner--live'}`}>
        <div>
          <div>{label}</div>
          {eventLabel ? <div className="state-viewer__hint">Event: {eventLabel}</div> : null}
        </div>
        {isTimeTravel && onExit ? (
          <button type="button" onClick={onExit} className="state-viewer__exit">
            Return to live
          </button>
        ) : null}
      </div>
      {loading ? (
        <div className="state-viewer__status">Loading snapshot…</div>
      ) : error ? (
        <div className="state-viewer__status state-viewer__status--error">{error}</div>
      ) : visibleKeys.length === 0 ? (
        <div className="state-viewer__status state-viewer__status--empty">No state captured yet.</div>
      ) : (
        <div className="state-viewer__body">
          <StateTree data={state} path="root" />
        </div>
      )}
    </div>
  );
}

'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import StepFilter, { useStepFilter } from './StepFilter';

function extractStepNumber(step: string): number | null {
  const match = step.match(/step[_\s]?(\d+)/i);
  return match ? parseInt(match[1], 10) : null;
}

interface PromptEvent {
  id: string;
  ts: number;
  step: string;
  direction: 'in' | 'out';
  fn_name: string;
  content: string;
  preview?: string;
  outputs?: Record<string, unknown>;
  keyExtractions?: Array<{ field: string; value: string; hasError?: boolean }>;
}

interface DBOperation {
  id: string;
  ts: number;
  step: string;
  operation: 'read' | 'write';
  table: string;
  key?: string;
  fields?: string[];
  summary: string;
}

interface AgentViewProps {
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
  prompt_preview?: string;
  detail?: Record<string, unknown> | string;
  row_id?: string;
}

// Key fields to highlight in extractions (primary entities)
const KEY_FIELDS = ['intent', 'date', 'event_date', 'email', 'participants', 'start_time', 'end_time', 'room', 'phone', 'name'];

export default function AgentView({ threadId, pollMs = 2000 }: AgentViewProps) {
  const [events, setEvents] = useState<PromptEvent[]>([]);
  const [dbOps, setDbOps] = useState<DBOperation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<'all' | 'in' | 'out'>('all');
  const [showDbOps, setShowDbOps] = useState(true);
  const { selectedStep } = useStepFilter();

  // Filter events by step and direction
  const filteredEvents = useMemo(() => {
    let filtered = events;
    if (selectedStep !== null) {
      filtered = filtered.filter((event) => {
        const stepNum = extractStepNumber(event.step);
        return stepNum === selectedStep;
      });
    }
    if (filter !== 'all') {
      filtered = filtered.filter((event) => event.direction === filter);
    }
    return filtered;
  }, [events, selectedStep, filter]);

  // Filter DB ops by step
  const filteredDbOps = useMemo(() => {
    if (selectedStep === null) return dbOps;
    return dbOps.filter((op) => {
      const stepNum = extractStepNumber(op.step);
      return stepNum === selectedStep;
    });
  }, [dbOps, selectedStep]);

  // Get available steps
  const availableSteps = useMemo(() => {
    const steps = new Set<number>();
    events.forEach((event) => {
      const stepNum = extractStepNumber(event.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    dbOps.forEach((op) => {
      const stepNum = extractStepNumber(op.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    return Array.from(steps).sort((a, b) => a - b);
  }, [events, dbOps]);

  // Latest extractions summary
  const extractionsSummary = useMemo(() => {
    const latest = new Map<string, { value: string; ts: number; hasError: boolean }>();
    // Process in chronological order (oldest first) so latest overwrites
    [...filteredEvents].reverse().forEach((event) => {
      if (event.direction === 'out' && event.keyExtractions) {
        event.keyExtractions.forEach(({ field, value, hasError }) => {
          if (value && value !== 'null' && value !== 'undefined') {
            latest.set(field, { value, ts: event.ts, hasError: hasError || false });
          }
        });
      }
    });
    return latest;
  }, [filteredEvents]);

  useEffect(() => {
    if (!threadId) {
      setEvents([]);
      setDbOps([]);
      return;
    }

    const controller = new AbortController();
    const fetchData = async () => {
      setLoading(true);
      try {
        const response = await fetch(
          `/api/debug/threads/${encodeURIComponent(threadId)}?granularity=verbose`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = await response.json();
        const trace = payload.trace || [];
        const { prompts, dbOperations } = extractData(trace);
        setEvents(prompts);
        setDbOps(dbOperations);
        setError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, pollMs);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [threadId, pollMs]);

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

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

  if (events.length === 0 && dbOps.length === 0 && !loading) {
    return (
      <div className="p-8 text-center text-slate-400">
        No LLM prompt events recorded yet.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <StepFilter availableSteps={availableSteps} />

      {/* Extractions Summary Card */}
      {extractionsSummary.size > 0 && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Extractions Summary (Latest Values)</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Array.from(extractionsSummary.entries()).map(([field, { value, hasError }]) => (
              <div key={field} className={`text-sm ${hasError ? 'bg-red-500/10 border-red-500/30' : 'bg-slate-900/50'} p-2 rounded border border-slate-700`}>
                <div className="text-xs text-slate-500">{field}</div>
                <div className={`font-mono truncate ${hasError ? 'text-red-400' : 'text-slate-200'}`} title={value}>
                  {value.length > 20 ? `${value.slice(0, 18)}...` : value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* DB Operations Section */}
      {filteredDbOps.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700 rounded-lg">
          <button
            type="button"
            onClick={() => setShowDbOps(!showDbOps)}
            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-800/50"
          >
            <h3 className="text-sm font-medium text-slate-300">
              Database Operations ({filteredDbOps.length})
            </h3>
            <span className="text-slate-500 text-sm">{showDbOps ? '\u25B2' : '\u25BC'}</span>
          </button>
          {showDbOps && (
            <div className="px-4 pb-4 space-y-2">
              {filteredDbOps.map((op) => (
                <div
                  key={op.id}
                  className={`flex items-center gap-3 px-3 py-2 rounded text-sm ${
                    op.operation === 'write'
                      ? 'bg-orange-500/10 border border-orange-500/20'
                      : 'bg-blue-500/10 border border-blue-500/20'
                  }`}
                >
                  <span className="text-xs text-slate-500 font-mono">{formatTime(op.ts)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    op.operation === 'write' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'
                  }`}>
                    {op.operation.toUpperCase()}
                  </span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                    {op.table}
                  </span>
                  <span className="text-slate-300 truncate flex-1">{op.summary}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Header with filter */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">LLM Prompts & Responses</h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">
            {selectedStep !== null ? `${filteredEvents.length} of ${events.length}` : filteredEvents.length} events
          </span>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as 'all' | 'in' | 'out')}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
          >
            <option value="all">All</option>
            <option value="in">Prompts Only</option>
            <option value="out">Responses Only</option>
          </select>
        </div>
      </div>

      {/* Event list */}
      <div className="space-y-3">
        {filteredEvents.map((event) => {
          const stepNum = extractStepNumber(event.step);
          const isExpanded = expandedIds.has(event.id);
          const isPrompt = event.direction === 'in';

          return (
            <div
              key={event.id}
              id={stepNum !== null ? `step-${stepNum}` : undefined}
              className={`border rounded-lg overflow-hidden ${
                isPrompt ? 'bg-blue-500/5 border-blue-500/20' : 'bg-green-500/5 border-green-500/20'
              }`}
            >
              {/* Summary row */}
              <button
                type="button"
                onClick={() => toggleExpanded(event.id)}
                className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-slate-800/30 transition-colors"
              >
                <span className="text-xs text-slate-500 font-mono">{formatTime(event.ts)}</span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{event.step}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${isPrompt ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'}`}>
                  {isPrompt ? '\u2192 Prompt' : '\u2190 Response'}
                </span>
                <span className="text-xs text-slate-500">{event.fn_name}</span>
                <span className="flex-1 text-sm text-slate-300 truncate">
                  {event.preview || event.content.slice(0, 80)}
                </span>
                <span className="text-slate-500 text-sm">{isExpanded ? '\u25B2' : '\u25BC'}</span>
              </button>

              {/* Expanded content */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-2 border-t border-slate-700/50 space-y-3">
                  {/* Key Extractions (for responses) - compact view */}
                  {!isPrompt && event.keyExtractions && event.keyExtractions.length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Key Extractions</div>
                      <div className="flex flex-wrap gap-2">
                        {event.keyExtractions.map(({ field, value, hasError }, idx) => (
                          <span
                            key={idx}
                            className={`text-xs px-2 py-1 rounded ${
                              hasError
                                ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                                : 'bg-green-500/10 text-green-400 border border-green-500/20'
                            }`}
                          >
                            <span className="text-slate-500">{field}:</span> {value || '(null)'}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Full content - collapsed by default for responses */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                      {isPrompt ? 'Prompt Text' : 'Response Text (Raw)'}
                    </div>
                    <pre className="text-sm text-slate-300 bg-slate-900/50 p-3 rounded font-mono whitespace-pre-wrap max-h-48 overflow-auto">
                      {event.content || '(empty)'}
                    </pre>
                  </div>

                  {/* Full Outputs - only show if user wants detail */}
                  {!isPrompt && event.outputs && Object.keys(event.outputs).length > 0 && (
                    <details className="group">
                      <summary className="text-xs text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-400">
                        Full Structured Output (click to expand)
                      </summary>
                      <pre className="text-xs text-slate-300 bg-slate-900/50 p-2 mt-2 rounded font-mono whitespace-pre-wrap max-h-64 overflow-auto">
                        {JSON.stringify(event.outputs, null, 2)}
                      </pre>
                    </details>
                  )}

                  {/* Copy button */}
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(event.content)}
                    className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
                  >
                    Copy to clipboard
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function extractData(trace: RawTraceEvent[]): { prompts: PromptEvent[]; dbOperations: DBOperation[] } {
  const prompts: PromptEvent[] = [];
  const dbOperations: DBOperation[] = [];

  trace.forEach((event, index) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};
    const id = event.row_id || `${event.ts}-${index}`;

    // Extract LLM prompts
    if (kind === 'AGENT_PROMPT_IN' || kind === 'AGENT_PROMPT_OUT') {
      const direction = kind === 'AGENT_PROMPT_IN' ? 'in' : 'out';

      let fn_name = '';
      if (typeof event.detail === 'object' && event.detail) {
        fn_name = (event.detail.label as string) || (event.detail.fn as string) || '';
      } else if (typeof event.detail === 'string') {
        fn_name = event.detail;
      }
      fn_name = fn_name || event.subject || '';

      const content =
        (data.prompt_text as string) ||
        (data.message_text as string) ||
        (data.reply_text as string) ||
        '';

      // Extract key fields from outputs for quick view
      let keyExtractions: Array<{ field: string; value: string; hasError?: boolean }> | undefined;
      if (direction === 'out' && data.outputs) {
        const outputs = data.outputs as Record<string, unknown>;
        keyExtractions = [];
        KEY_FIELDS.forEach((field) => {
          if (field in outputs) {
            const val = outputs[field];
            const strVal = val === null ? '(null)' : String(val);
            // Flag potentially problematic extractions
            const hasError = (field === 'city' && strVal.toLowerCase().includes('february')) ||
                           (field === 'phone' && /^20\d{8}$/.test(strVal)); // Phone looks like date
            keyExtractions!.push({ field, value: strVal, hasError });
          }
        });
      }

      prompts.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        direction,
        fn_name,
        content,
        preview: event.prompt_preview,
        outputs: direction === 'out' ? (data.outputs as Record<string, unknown>) : undefined,
        keyExtractions,
      });
    }

    // Extract DB operations
    if (kind === 'DB_READ' || kind === 'DB_WRITE') {
      const table = (data.table as string) || (event.subject as string) || 'unknown';
      const operation = kind === 'DB_WRITE' ? 'write' : 'read';
      const fields = data.fields as string[] | undefined;
      const key = (data.key as string) || (data.id as string) || '';

      let summary = '';
      if (operation === 'write') {
        summary = fields ? `Updated: ${fields.join(', ')}` : `Write to ${table}`;
      } else {
        summary = key ? `Read ${key}` : `Read from ${table}`;
      }

      dbOperations.push({
        id: `db-${id}`,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        operation,
        table,
        key,
        fields,
        summary,
      });
    }

    // Also look for events with "DB" in kind or subject for broader capture
    if ((kind.includes('DB_') || (event.subject || '').includes('db.')) && !kind.match(/^DB_(READ|WRITE)$/)) {
      const isWrite = kind.includes('WRITE') || kind.includes('UPDATE') || kind.includes('CREATE');
      const table = (event.subject || '').replace('db.', '').split('.')[0] || kind;

      dbOperations.push({
        id: `db-${id}`,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        operation: isWrite ? 'write' : 'read',
        table,
        summary: event.subject || kind,
      });
    }
  });

  return {
    prompts: prompts.reverse(),
    dbOperations: dbOperations.reverse(),
  };
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

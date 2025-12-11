'use client';

import { useEffect, useState, useCallback } from 'react';

interface PromptEvent {
  id: string;
  ts: number;
  step: string;
  direction: 'in' | 'out';
  fn_name: string;
  content: string;
  preview?: string;
  outputs?: Record<string, unknown>;
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

export default function AgentView({ threadId, pollMs = 2000 }: AgentViewProps) {
  const [events, setEvents] = useState<PromptEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<'all' | 'in' | 'out'>('all');

  useEffect(() => {
    if (!threadId) {
      setEvents([]);
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
        const prompts = extractPrompts(trace);
        setEvents(prompts);
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
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const filteredEvents = events.filter((e) => filter === 'all' || e.direction === filter);

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

  if (events.length === 0 && !loading) {
    return (
      <div className="p-8 text-center text-slate-400">
        No LLM prompt events recorded yet.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header with filter */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">LLM Prompts & Responses</h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">{filteredEvents.length} events</span>
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
          const isExpanded = expandedIds.has(event.id);
          const isPrompt = event.direction === 'in';

          return (
            <div
              key={event.id}
              className={`border rounded-lg overflow-hidden ${
                isPrompt
                  ? 'bg-blue-500/5 border-blue-500/20'
                  : 'bg-green-500/5 border-green-500/20'
              }`}
            >
              {/* Summary row */}
              <button
                type="button"
                onClick={() => toggleExpanded(event.id)}
                className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-slate-800/30 transition-colors"
              >
                <span className="text-xs text-slate-500 font-mono">
                  {formatTime(event.ts)}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                  {event.step}
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    isPrompt
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-green-500/20 text-green-400'
                  }`}
                >
                  {isPrompt ? '\u2192 Prompt' : '\u2190 Response'}
                </span>
                <span className="text-xs text-slate-500">{event.fn_name}</span>
                <span className="flex-1 text-sm text-slate-300 truncate">
                  {event.preview || event.content.slice(0, 80)}
                </span>
                <span className="text-slate-500 text-sm">
                  {isExpanded ? '\u25B2' : '\u25BC'}
                </span>
              </button>

              {/* Expanded content */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-2 border-t border-slate-700/50 space-y-3">
                  {/* Full content */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                      {isPrompt ? 'Prompt Text' : 'Response Text'}
                    </div>
                    <pre className="text-sm text-slate-300 bg-slate-900/50 p-3 rounded font-mono whitespace-pre-wrap max-h-96 overflow-auto">
                      {event.content || '(empty)'}
                    </pre>
                  </div>

                  {/* Outputs (for responses) */}
                  {!isPrompt && event.outputs && Object.keys(event.outputs).length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                        Structured Outputs
                      </div>
                      <pre className="text-sm text-slate-300 bg-slate-900/50 p-3 rounded font-mono whitespace-pre-wrap max-h-48 overflow-auto">
                        {JSON.stringify(event.outputs, null, 2)}
                      </pre>
                    </div>
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

function extractPrompts(trace: RawTraceEvent[]): PromptEvent[] {
  const prompts: PromptEvent[] = [];

  trace.forEach((event, index) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};

    if (kind === 'AGENT_PROMPT_IN' || kind === 'AGENT_PROMPT_OUT') {
      const id = event.row_id || `${event.ts}-${index}`;
      const direction = kind === 'AGENT_PROMPT_IN' ? 'in' : 'out';

      // Extract function name from detail
      let fn_name = '';
      if (typeof event.detail === 'object' && event.detail) {
        fn_name = (event.detail.label as string) || (event.detail.fn as string) || '';
      } else if (typeof event.detail === 'string') {
        fn_name = event.detail;
      }
      fn_name = fn_name || event.subject || '';

      // Extract content
      const content =
        (data.prompt_text as string) ||
        (data.message_text as string) ||
        (data.reply_text as string) ||
        '';

      prompts.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        direction,
        fn_name,
        content,
        preview: event.prompt_preview,
        outputs: direction === 'out' ? (data.outputs as Record<string, unknown>) : undefined,
      });
    }
  });

  return prompts.reverse(); // Most recent first
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

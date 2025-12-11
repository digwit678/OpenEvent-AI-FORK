'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';

interface ClassificationEvent {
  id: string;
  ts: number;
  step: string;
  classification_type: string;
  raw_input: string;
  matched_patterns: string[];
  result: string;
  confidence?: number;
  alternatives?: string[];
  expanded?: boolean;
}

interface DetectionViewProps {
  threadId: string | null;
  pollMs?: number;
}

interface RawTraceEvent {
  ts?: number;
  kind?: string;
  step?: string;
  owner_step?: string;
  subject?: string;
  summary?: string;
  data?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  entity_context?: Record<string, unknown>;
  row_id?: string;
}

export default function DetectionView({ threadId, pollMs = 2000 }: DetectionViewProps) {
  const [events, setEvents] = useState<ClassificationEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Fetch and extract classification events from trace
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

        // Extract classification-related events
        const classifications = extractClassifications(trace);
        setEvents(classifications);
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
        No classification events recorded yet.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Classification History</h2>
        <span className="text-sm text-slate-400">{events.length} events</span>
      </div>

      <div className="space-y-3">
        {events.map((event) => {
          const isExpanded = expandedIds.has(event.id);
          return (
            <div
              key={event.id}
              className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden"
            >
              {/* Summary row - always visible */}
              <button
                type="button"
                onClick={() => toggleExpanded(event.id)}
                className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-slate-800/80 transition-colors"
              >
                <span className="text-xs text-slate-500 font-mono">
                  {formatTime(event.ts)}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                  {event.step}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-400">
                  {event.classification_type}
                </span>
                <span className="flex-1 text-sm text-slate-200 truncate">
                  {event.result}
                </span>
                {event.confidence !== undefined && (
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      event.confidence > 0.8
                        ? 'bg-green-500/20 text-green-400'
                        : event.confidence > 0.5
                        ? 'bg-yellow-500/20 text-yellow-400'
                        : 'bg-red-500/20 text-red-400'
                    }`}
                  >
                    {(event.confidence * 100).toFixed(0)}%
                  </span>
                )}
                <span className="text-slate-500 text-sm">
                  {isExpanded ? '\u25B2' : '\u25BC'}
                </span>
              </button>

              {/* Expanded details */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-2 border-t border-slate-700 space-y-3">
                  {/* Raw input */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                      Input Message
                    </div>
                    <div className="text-sm text-slate-300 bg-slate-900/50 p-2 rounded font-mono">
                      {event.raw_input || '(empty)'}
                    </div>
                  </div>

                  {/* Matched patterns */}
                  {event.matched_patterns.length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                        Matched Patterns ({event.matched_patterns.length})
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {event.matched_patterns.map((pattern, idx) => (
                          <span
                            key={idx}
                            className="text-xs px-2 py-1 rounded bg-green-500/10 text-green-400 border border-green-500/20"
                          >
                            {pattern}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Alternatives considered */}
                  {event.alternatives && event.alternatives.length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                        Alternatives Considered
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {event.alternatives.map((alt, idx) => (
                          <span
                            key={idx}
                            className="text-xs px-2 py-1 rounded bg-slate-700 text-slate-400"
                          >
                            {alt}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Final result */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                      Final Classification
                    </div>
                    <div className="text-sm font-medium text-blue-400">
                      {event.result}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Helper to extract classification events from raw trace
function extractClassifications(trace: RawTraceEvent[]): ClassificationEvent[] {
  const classifications: ClassificationEvent[] = [];

  trace.forEach((event, index) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};

    // Look for classification-related events
    if (
      kind.includes('CLASSIFY') ||
      kind.includes('INTENT') ||
      kind.includes('ENTITY_CAPTURE') ||
      kind === 'AGENT_PROMPT_OUT'
    ) {
      const id = event.row_id || `${event.ts}-${index}`;

      // Extract relevant fields based on event type
      let classification_type = 'unknown';
      let result = '';
      let raw_input = '';
      let matched_patterns: string[] = [];
      let alternatives: string[] = [];
      let confidence: number | undefined;

      if (kind.includes('INTENT') || kind.includes('CLASSIFY')) {
        classification_type = 'intent';
        result = (data.intent as string) || (data.result as string) || event.subject || '';
        raw_input = (data.message as string) || (data.raw_input as string) || '';
        matched_patterns = (data.matched_patterns as string[]) || [];
        alternatives = (data.alternatives as string[]) || [];
        confidence = data.confidence as number | undefined;
      } else if (kind === 'ENTITY_CAPTURE') {
        const entityCtx = event.entity_context || {};
        classification_type = 'entity';
        result = `${entityCtx.key || event.subject}: ${entityCtx.value || ''}`;
        raw_input = (data.source_text as string) || '';
        matched_patterns = (data.parser_used as string) ? [data.parser_used as string] : [];
      } else if (kind === 'AGENT_PROMPT_OUT') {
        // Look for classification outputs in LLM responses
        const outputs = data.outputs as Record<string, unknown> | undefined;
        if (outputs && (outputs.intent || outputs.classification)) {
          classification_type = 'llm_classification';
          result = (outputs.intent as string) || (outputs.classification as string) || '';
          raw_input = (data.prompt_text as string) || '';
          confidence = outputs.confidence as number | undefined;
        } else {
          return; // Skip non-classification prompt outputs
        }
      }

      if (result) {
        classifications.push({
          id,
          ts: event.ts || 0,
          step: event.step || event.owner_step || '',
          classification_type,
          raw_input,
          matched_patterns,
          result,
          confidence,
          alternatives,
        });
      }
    }
  });

  return classifications.reverse(); // Most recent first
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

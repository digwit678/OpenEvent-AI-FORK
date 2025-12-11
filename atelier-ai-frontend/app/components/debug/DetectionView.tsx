'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import StepFilter, { useStepFilter } from './StepFilter';

interface DetectionEvent {
  id: string;
  ts: number;
  step: string;
  detection_stage: 'regex' | 'ner' | 'llm' | 'unknown';
  detection_type: 'intent' | 'entity' | 'confirmation' | 'other';
  field_name: string;
  raw_input: string;
  extracted_value: string;
  confidence?: number;
  patterns_checked?: string[];
  patterns_matched?: string[];
  alternatives?: string[];
  error?: string;
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

function extractStepNumber(step: string): number | null {
  const match = step.match(/step[_\s]?(\d+)/i);
  return match ? parseInt(match[1], 10) : null;
}

const STAGE_COLORS = {
  regex: { bg: 'bg-blue-500/20', text: 'text-blue-400', label: 'Regex' },
  ner: { bg: 'bg-purple-500/20', text: 'text-purple-400', label: 'NER' },
  llm: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'LLM' },
  unknown: { bg: 'bg-slate-500/20', text: 'text-slate-400', label: '?' },
};

const TYPE_COLORS = {
  intent: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
  entity: { bg: 'bg-cyan-500/20', text: 'text-cyan-400' },
  confirmation: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  other: { bg: 'bg-slate-500/20', text: 'text-slate-400' },
};

export default function DetectionView({ threadId, pollMs = 2000 }: DetectionViewProps) {
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'timeline' | 'summary'>('timeline');
  const { selectedStep } = useStepFilter();

  // Filter events by selected step
  const filteredEvents = useMemo(() => {
    if (selectedStep === null) return events;
    return events.filter((event) => {
      const stepNum = extractStepNumber(event.step);
      return stepNum === selectedStep;
    });
  }, [events, selectedStep]);

  // Get available steps
  const availableSteps = useMemo(() => {
    const steps = new Set<number>();
    events.forEach((event) => {
      const stepNum = extractStepNumber(event.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    return Array.from(steps).sort((a, b) => a - b);
  }, [events]);

  // Group events by field for summary view
  const summaryByField = useMemo(() => {
    const grouped = new Map<string, DetectionEvent[]>();
    filteredEvents.forEach((event) => {
      const key = event.field_name || 'unknown';
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key)!.push(event);
    });
    return grouped;
  }, [filteredEvents]);

  // Stats
  const stats = useMemo(() => {
    const byStage = { regex: 0, ner: 0, llm: 0, unknown: 0 };
    const byType = { intent: 0, entity: 0, confirmation: 0, other: 0 };
    filteredEvents.forEach((e) => {
      byStage[e.detection_stage]++;
      byType[e.detection_type]++;
    });
    return { byStage, byType };
  }, [filteredEvents]);

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
        const detections = extractDetections(trace);
        setEvents(detections);
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <StepFilter availableSteps={availableSteps} />

      {/* Stats Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '13px', color: '#64748b', fontWeight: '500' }}>Stage:</span>
          {Object.entries(stats.byStage).map(([stage, count]) => count > 0 && (
            <span
              key={stage}
              style={{
                fontSize: '13px',
                padding: '4px 10px',
                borderRadius: '8px',
                backgroundColor: STAGE_COLORS[stage as keyof typeof STAGE_COLORS].bg.includes('blue') ? 'rgba(59,130,246,0.2)' :
                                STAGE_COLORS[stage as keyof typeof STAGE_COLORS].bg.includes('purple') ? 'rgba(168,85,247,0.2)' :
                                STAGE_COLORS[stage as keyof typeof STAGE_COLORS].bg.includes('green') ? 'rgba(34,197,94,0.2)' : 'rgba(100,116,139,0.2)',
                color: stage === 'regex' ? '#60a5fa' : stage === 'ner' ? '#c084fc' : stage === 'llm' ? '#4ade80' : '#94a3b8',
                fontWeight: '500'
              }}
            >
              {STAGE_COLORS[stage as keyof typeof STAGE_COLORS].label}: {count}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '13px', color: '#64748b', fontWeight: '500' }}>Type:</span>
          {Object.entries(stats.byType).map(([type, count]) => count > 0 && (
            <span
              key={type}
              style={{
                fontSize: '13px',
                padding: '4px 10px',
                borderRadius: '8px',
                backgroundColor: type === 'intent' ? 'rgba(249,115,22,0.2)' :
                                type === 'entity' ? 'rgba(6,182,212,0.2)' :
                                type === 'confirmation' ? 'rgba(234,179,8,0.2)' : 'rgba(100,116,139,0.2)',
                color: type === 'intent' ? '#fb923c' : type === 'entity' ? '#22d3ee' : type === 'confirmation' ? '#facc15' : '#94a3b8',
                fontWeight: '500'
              }}
            >
              {type}: {count}
            </span>
          ))}
        </div>
      </div>

      {/* View Toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: '600', color: '#e2e8f0', margin: 0 }}>Detection Pipeline</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '14px', color: '#94a3b8' }}>
            {selectedStep !== null ? `${filteredEvents.length} of ${events.length}` : filteredEvents.length} events
          </span>
          <div style={{ display: 'flex', backgroundColor: '#1e293b', borderRadius: '10px', overflow: 'hidden', border: '1px solid #334155' }}>
            <button
              type="button"
              onClick={() => setViewMode('timeline')}
              style={{
                padding: '8px 16px',
                fontSize: '14px',
                fontWeight: '500',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: viewMode === 'timeline' ? '#334155' : 'transparent',
                color: viewMode === 'timeline' ? '#f1f5f9' : '#94a3b8'
              }}
            >
              Timeline
            </button>
            <button
              type="button"
              onClick={() => setViewMode('summary')}
              style={{
                padding: '8px 16px',
                fontSize: '14px',
                fontWeight: '500',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: viewMode === 'summary' ? '#334155' : 'transparent',
                color: viewMode === 'summary' ? '#f1f5f9' : '#94a3b8'
              }}
            >
              By Field
            </button>
          </div>
        </div>
      </div>

      {events.length === 0 && !loading ? (
        <div style={{ padding: '48px', textAlign: 'center', color: '#94a3b8', fontSize: '15px' }}>
          No detection events recorded yet.
        </div>
      ) : viewMode === 'summary' ? (
        /* Summary View - Grouped by Field */
        <div className="space-y-4">
          {Array.from(summaryByField.entries()).map(([field, fieldEvents]) => (
            <div key={field} className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="font-medium text-slate-200">{field}</span>
                <span className="text-xs text-slate-500">{fieldEvents.length} detection(s)</span>
              </div>
              <div className="space-y-2">
                {fieldEvents.map((event) => (
                  <div key={event.id} className="flex items-center gap-3 text-sm">
                    <span className="text-xs text-slate-500 font-mono w-16">{formatTime(event.ts)}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${STAGE_COLORS[event.detection_stage].bg} ${STAGE_COLORS[event.detection_stage].text}`}>
                      {STAGE_COLORS[event.detection_stage].label}
                    </span>
                    <span className="text-slate-300 truncate flex-1">{event.extracted_value || '(none)'}</span>
                    {event.confidence !== undefined && (
                      <span className={`text-xs ${event.confidence > 0.7 ? 'text-green-400' : event.confidence > 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {(event.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Timeline View */
        <div className="space-y-2">
          {filteredEvents.map((event) => {
            const stepNum = extractStepNumber(event.step);
            const isExpanded = expandedIds.has(event.id);
            const stageColor = STAGE_COLORS[event.detection_stage];
            const typeColor = TYPE_COLORS[event.detection_type];

            return (
              <div
                key={event.id}
                id={stepNum !== null ? `step-${stepNum}` : undefined}
                className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggleExpanded(event.id)}
                  className="w-full px-4 py-2 flex items-center gap-3 text-left hover:bg-slate-800/80 transition-colors"
                >
                  <span className="text-xs text-slate-500 font-mono w-16 flex-shrink-0">
                    {formatTime(event.ts)}
                  </span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                    {event.step}
                  </span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${stageColor.bg} ${stageColor.text}`}>
                    {stageColor.label}
                  </span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${typeColor.bg} ${typeColor.text}`}>
                    {event.detection_type}
                  </span>
                  <span className="text-xs text-slate-400 w-24 flex-shrink-0 truncate">
                    {event.field_name}
                  </span>
                  <span className="flex-1 text-sm text-slate-200 truncate">
                    {event.extracted_value || '(none)'}
                  </span>
                  {event.confidence !== undefined && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      event.confidence > 0.7 ? 'bg-green-500/20 text-green-400' :
                      event.confidence > 0.4 ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {(event.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  <span className="text-slate-500 text-sm">{isExpanded ? '\u25B2' : '\u25BC'}</span>
                </button>

                {isExpanded && (
                  <div className="px-4 pb-4 pt-2 border-t border-slate-700 space-y-3">
                    {/* Input that triggered detection */}
                    {event.raw_input && (
                      <div>
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                          Input Text
                        </div>
                        <div className="text-sm text-slate-300 bg-slate-900/50 p-2 rounded font-mono whitespace-pre-wrap max-h-32 overflow-auto">
                          {event.raw_input}
                        </div>
                      </div>
                    )}

                    {/* Patterns checked (for regex stage) */}
                    {event.patterns_matched && event.patterns_matched.length > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                          Patterns Matched
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {event.patterns_matched.map((p, i) => (
                            <span key={i} className="text-xs px-2 py-0.5 rounded bg-green-500/10 text-green-400 border border-green-500/20">
                              {p}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Extracted value */}
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                        Extracted Value
                      </div>
                      <div className="text-sm font-medium text-blue-400">
                        {event.extracted_value || '(none)'}
                      </div>
                    </div>

                    {/* Alternatives */}
                    {event.alternatives && event.alternatives.length > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                          Alternatives Considered
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {event.alternatives.map((alt, i) => (
                            <span key={i} className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-400">
                              {alt}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Error if any */}
                    {event.error && (
                      <div className="text-xs text-red-400 bg-red-500/10 p-2 rounded">
                        Error: {event.error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div style={{
        backgroundColor: 'rgba(30,41,59,0.3)',
        border: '1px solid #334155',
        borderRadius: '12px',
        padding: '16px 20px'
      }}>
        <div style={{ fontWeight: '600', color: '#cbd5e1', marginBottom: '12px', fontSize: '14px' }}>Detection Pipeline Stages</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '24px', fontSize: '14px', color: '#94a3b8' }}>
          <div><span style={{ color: '#60a5fa', fontWeight: '500' }}>Regex</span> - Pattern matching (fastest, first checked)</div>
          <div><span style={{ color: '#c084fc', fontWeight: '500' }}>NER</span> - Named Entity Recognition</div>
          <div><span style={{ color: '#4ade80', fontWeight: '500' }}>LLM</span> - AI extraction (slowest, most flexible)</div>
        </div>
      </div>
    </div>
  );
}

function extractDetections(trace: RawTraceEvent[]): DetectionEvent[] {
  const detections: DetectionEvent[] = [];

  trace.forEach((event, index) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};
    const id = event.row_id || `${event.ts}-${index}`;

    // Entity captures (from extraction pipeline)
    if (kind === 'ENTITY_CAPTURE' || kind === 'ENTITY_SUPERSEDED') {
      const entityCtx = event.entity_context || {};
      const parserUsed = (data.parser_used as string) || '';

      detections.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        detection_stage: parserUsed.includes('regex') ? 'regex' :
                        parserUsed.includes('ner') ? 'ner' :
                        parserUsed.includes('llm') ? 'llm' : 'unknown',
        detection_type: 'entity',
        field_name: (entityCtx.key as string) || event.subject || 'unknown',
        raw_input: (data.source_text as string) || (data.raw_input as string) || '',
        extracted_value: String(entityCtx.value || ''),
        patterns_matched: parserUsed ? [parserUsed] : [],
      });
    }

    // Intent classification
    if (kind.includes('INTENT') || kind.includes('CLASSIFY')) {
      detections.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        detection_stage: 'llm',
        detection_type: 'intent',
        field_name: 'intent',
        raw_input: (data.message as string) || (data.raw_input as string) || '',
        extracted_value: (data.intent as string) || (data.result as string) || event.subject || '',
        confidence: data.confidence as number | undefined,
        alternatives: data.alternatives as string[] | undefined,
        patterns_matched: data.matched_patterns as string[] | undefined,
      });
    }

    // LLM extraction responses (agent extractor)
    if (kind === 'AGENT_PROMPT_OUT') {
      const outputs = data.outputs as Record<string, unknown> | undefined;
      if (outputs) {
        // Check if it's an intent classification
        if (outputs.intent !== undefined) {
          detections.push({
            id: `${id}-intent`,
            ts: event.ts || 0,
            step: event.step || event.owner_step || '',
            detection_stage: 'llm',
            detection_type: 'intent',
            field_name: 'intent',
            raw_input: (data.prompt_text as string) || '',
            extracted_value: String(outputs.intent || ''),
            confidence: outputs.confidence as number | undefined,
          });
        }

        // Extract individual entity extractions from outputs
        const entityFields = ['date', 'email', 'participants', 'phone', 'event_date',
          'start_time', 'end_time', 'room', 'layout', 'name', 'company', 'city'];

        entityFields.forEach((field) => {
          if (outputs[field] !== null && outputs[field] !== undefined) {
            detections.push({
              id: `${id}-${field}`,
              ts: event.ts || 0,
              step: event.step || event.owner_step || '',
              detection_stage: 'llm',
              detection_type: 'entity',
              field_name: field,
              raw_input: (data.prompt_text as string) || '',
              extracted_value: String(outputs[field]),
            });
          }
        });
      }
    }
  });

  return detections.reverse();
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

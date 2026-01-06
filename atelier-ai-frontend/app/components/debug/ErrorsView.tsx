'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { detectProblems, Problem } from './ProblemBanner';
import StepFilter, { useStepFilter } from './StepFilter';

function extractStepNumber(step: string): number | null {
  const match = step.match(/step[_\s]?(\d+)/i);
  return match ? parseInt(match[1], 10) : null;
}

interface ErrorsViewProps {
  threadId: string | null;
  pollMs?: number;
}

interface DetourEvent {
  ts: number;
  from_step: string;
  to_step: string;
  reason: string;
}

interface GateFailure {
  ts: number;
  step: string;
  gate: string;
  missing: string[];
}

interface RawTraceEvent {
  ts?: number;
  kind?: string;
  step?: string;
  owner_step?: string;
  gate?: { label?: string; missing?: string[] };
  detour?: { from_step?: string; to_step?: string; reason?: string };
  data?: Record<string, unknown>;
}

export default function ErrorsView({ threadId, pollMs = 2000 }: ErrorsViewProps) {
  const [problems, setProblems] = useState<Problem[]>([]);
  const [detours, setDetours] = useState<DetourEvent[]>([]);
  const [gateFailures, setGateFailures] = useState<GateFailure[]>([]);
  const [state, setState] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [diagnosisCopied, setDiagnosisCopied] = useState(false);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);
  const { selectedStep } = useStepFilter();

  // Filter gate failures by selected step
  const filteredGateFailures = useMemo(() => {
    if (selectedStep === null) return gateFailures;
    return gateFailures.filter((gate) => {
      const stepNum = extractStepNumber(gate.step);
      return stepNum === selectedStep;
    });
  }, [gateFailures, selectedStep]);

  // Filter detours by selected step
  const filteredDetours = useMemo(() => {
    if (selectedStep === null) return detours;
    return detours.filter((detour) => {
      const fromNum = extractStepNumber(detour.from_step);
      const toNum = extractStepNumber(detour.to_step);
      return fromNum === selectedStep || toNum === selectedStep;
    });
  }, [detours, selectedStep]);

  // Get available steps
  const availableSteps = useMemo(() => {
    const steps = new Set<number>();
    gateFailures.forEach((gate) => {
      const stepNum = extractStepNumber(gate.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    detours.forEach((detour) => {
      const fromNum = extractStepNumber(detour.from_step);
      const toNum = extractStepNumber(detour.to_step);
      if (fromNum !== null) steps.add(fromNum);
      if (toNum !== null) steps.add(toNum);
    });
    return Array.from(steps).sort((a, b) => a - b);
  }, [gateFailures, detours]);

  useEffect(() => {
    if (!threadId) {
      setProblems([]);
      setDetours([]);
      setGateFailures([]);
      setState({});
      return;
    }

    const controller = new AbortController();
    const fetchData = async () => {
      try {
        const response = await fetch(
          `/api/debug/threads/${encodeURIComponent(threadId)}?granularity=verbose`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = await response.json();
        setState(payload.state || {});

        // Extract problems from state
        const detectedProblems = detectProblems(payload.state || {});

        // Extract detours and gate failures from trace
        const trace = payload.trace || [];
        const extractedDetours: DetourEvent[] = [];
        const extractedGates: GateFailure[] = [];

        // Count detour pairs for loop detection
        const detourPairs = new Map<string, number>();

        trace.forEach((event: RawTraceEvent) => {
          if (event.kind === 'DETOUR' && event.detour) {
            const pair = `${event.detour.from_step}->${event.detour.to_step}`;
            detourPairs.set(pair, (detourPairs.get(pair) || 0) + 1);

            extractedDetours.push({
              ts: event.ts || 0,
              from_step: event.detour.from_step || '',
              to_step: event.detour.to_step || '',
              reason: event.detour.reason || '',
            });
          }
          if (event.kind === 'GATE_FAIL' && event.gate) {
            extractedGates.push({
              ts: event.ts || 0,
              step: event.step || event.owner_step || '',
              gate: event.gate.label || '',
              missing: event.gate.missing || [],
            });
          }
        });

        // Add detour loop problem if detected
        detourPairs.forEach((count, pair) => {
          if (count > 2) {
            detectedProblems.push({
              id: `detour_loop_${pair}`,
              type: 'detour_loop',
              message: `Detour loop detected: ${pair} (${count} times)`,
              severity: 'warn',
            });
          }
        });

        setProblems(detectedProblems);
        setDetours(extractedDetours.reverse().slice(0, 10)); // Last 10
        setGateFailures(extractedGates.reverse().slice(0, 10)); // Last 10
        setError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      }
    };

    fetchData();
    const interval = setInterval(fetchData, pollMs);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [threadId, pollMs]);

  const copyLLMDiagnosis = useCallback(async () => {
    if (!threadId) return;

    setDiagnosisLoading(true);
    try {
      const response = await fetch(
        `/api/debug/threads/${encodeURIComponent(threadId)}/llm-diagnosis`
      );
      if (!response.ok) {
        throw new Error('Failed to generate diagnosis');
      }
      const text = await response.text();
      await navigator.clipboard.writeText(text);
      setDiagnosisCopied(true);
      setTimeout(() => setDiagnosisCopied(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copy failed');
    } finally {
      setDiagnosisLoading(false);
    }
  }, [threadId]);

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
    <div className="space-y-6">
      <StepFilter availableSteps={availableSteps} />

      {/* LLM Diagnosis Copy */}
      <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-medium text-purple-400">LLM Diagnosis</h3>
            <p className="text-sm text-slate-400 mt-1">
              Copy a formatted diagnosis for AI-assisted debugging
            </p>
          </div>
          <button
            type="button"
            onClick={copyLLMDiagnosis}
            disabled={diagnosisLoading}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              diagnosisCopied
                ? 'bg-green-500/20 text-green-400'
                : 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30'
            }`}
          >
            {diagnosisLoading ? 'Generating...' : diagnosisCopied ? 'Copied!' : 'Copy LLM Diagnosis'}
          </button>
        </div>
      </div>

      {/* Active Problems */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Active Problems</h2>
        {problems.length === 0 ? (
          <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4 text-green-400">
            No problems detected
          </div>
        ) : (
          <div className="space-y-2">
            {problems.map((problem) => (
              <div
                key={problem.id}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${
                  problem.severity === 'error'
                    ? 'bg-red-500/10 border-red-500/30 text-red-400'
                    : problem.severity === 'warn'
                    ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
                    : 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                }`}
              >
                <span className="text-lg">
                  {problem.type === 'hash_mismatch' && '⚠'}
                  {problem.type === 'detour_loop' && '↻'}
                  {problem.type === 'stuck' && '⏸'}
                  {problem.type === 'date_inconsistency' && '📅'}
                  {problem.type === 'hil_violation' && '🚫'}
                </span>
                <span className="flex-1">{problem.message}</span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                  {problem.type}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent Gate Failures */}
      <div>
        <h2 className="text-lg font-semibold mb-3">
          Recent Gate Failures
          {selectedStep !== null && (
            <span className="text-sm font-normal text-slate-400 ml-2">
              ({filteredGateFailures.length} of {gateFailures.length})
            </span>
          )}
        </h2>
        {filteredGateFailures.length === 0 ? (
          <div className="text-slate-400 text-sm">No gate failures recorded</div>
        ) : (
          <div className="space-y-2">
            {filteredGateFailures.map((gate, idx) => {
              const stepNum = extractStepNumber(gate.step);
              return (
              <div
                key={idx}
                id={stepNum !== null ? `step-${stepNum}` : undefined}
                className="bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 flex items-center gap-4"
              >
                <span className="text-xs text-slate-500 font-mono">
                  {formatTime(gate.ts)}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                  {gate.step}
                </span>
                <span className="text-sm text-slate-300">{gate.gate}</span>
                {gate.missing.length > 0 && (
                  <span className="text-xs text-red-400">
                    Missing: {gate.missing.join(', ')}
                  </span>
                )}
              </div>
            );
            })}
          </div>
        )}
      </div>

      {/* Recent Detours */}
      <div>
        <h2 className="text-lg font-semibold mb-3">
          Recent Detours
          {selectedStep !== null && (
            <span className="text-sm font-normal text-slate-400 ml-2">
              ({filteredDetours.length} of {detours.length})
            </span>
          )}
        </h2>
        {filteredDetours.length === 0 ? (
          <div className="text-slate-400 text-sm">No detours recorded</div>
        ) : (
          <div className="space-y-2">
            {filteredDetours.map((detour, idx) => {
              const fromNum = extractStepNumber(detour.from_step);
              return (
              <div
                key={idx}
                id={fromNum !== null ? `step-${fromNum}` : undefined}
                className="bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-4 py-3 flex items-center gap-4"
              >
                <span className="text-xs text-slate-500 font-mono">
                  {formatTime(detour.ts)}
                </span>
                <span className="text-sm text-yellow-400">
                  {detour.from_step} → {detour.to_step}
                </span>
                <span className="text-xs text-slate-400 flex-1 truncate">
                  {detour.reason}
                </span>
              </div>
            );
            })}
          </div>
        )}
      </div>

      {/* Key State Values */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Key State Values</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <StateCard label="requirements_hash" value={state.requirements_hash} />
          <StateCard label="room_eval_hash" value={state.room_eval_hash} />
          <StateCard
            label="Hash Match"
            value={state.requirements_hash === state.room_eval_hash ? 'Yes' : 'No'}
            highlight={state.requirements_hash !== state.room_eval_hash}
          />
          <StateCard label="chosen_date" value={state.chosen_date} />
          <StateCard label="date_confirmed" value={state.date_confirmed} />
          <StateCard label="locked_room_id" value={state.locked_room_id} />
          <StateCard label="current_step" value={state.current_step || state.step} />
          <StateCard label="thread_state" value={state.thread_state} />
          <StateCard label="hil_open" value={state.hil_open} />
        </div>
      </div>
    </div>
  );
}

function StateCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: unknown;
  highlight?: boolean;
}) {
  const displayValue = value === undefined || value === null ? '(not set)' : String(value);
  const isSet = value !== undefined && value !== null;

  return (
    <div
      className={`px-3 py-2 rounded-lg border ${
        highlight
          ? 'bg-red-500/10 border-red-500/30'
          : isSet
          ? 'bg-slate-800/50 border-slate-700'
          : 'bg-slate-900/30 border-slate-800'
      }`}
    >
      <div className="text-xs text-slate-500 truncate">{label}</div>
      <div
        className={`text-sm font-mono truncate ${
          highlight ? 'text-red-400' : isSet ? 'text-slate-200' : 'text-slate-500'
        }`}
      >
        {displayValue.length > 20 ? `${displayValue.slice(0, 17)}...` : displayValue}
      </div>
    </div>
  );
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

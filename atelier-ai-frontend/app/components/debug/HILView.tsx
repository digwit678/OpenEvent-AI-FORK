'use client';

import { useEffect, useState } from 'react';

interface HILTask {
  ts: number;
  task_type: string;
  action: string;
  step: string;
  payload_keys?: string[];
  violation?: boolean;
  violation_reason?: string;
}

interface HILViewProps {
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
}

const STEP_REQUIREMENTS: Record<string, number> = {
  date_confirm: 2,
  room_approve: 3,
  offer_review: 4,
  deposit_request: 4,
  confirmation: 5,
};

export default function HILView({ threadId, pollMs = 2000 }: HILViewProps) {
  const [tasks, setTasks] = useState<HILTask[]>([]);
  const [hilOpen, setHilOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!threadId) {
      setTasks([]);
      setHilOpen(false);
      setCurrentStep(null);
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
        const state = payload.state || {};
        const trace = payload.trace || [];

        setHilOpen(Boolean(state.hil_open));
        const step = state.current_step || state.step;
        setCurrentStep(typeof step === 'number' ? step : parseInt(step, 10) || null);

        // Extract HIL-related events
        const hilTasks = extractHILTasks(trace, currentStep);
        setTasks(hilTasks);
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
  }, [threadId, pollMs, currentStep]);

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

  const violations = tasks.filter((t) => t.violation);

  return (
    <div className="space-y-6">
      {/* Current HIL Status */}
      <div className={`p-4 rounded-lg border ${
        hilOpen
          ? 'bg-yellow-500/10 border-yellow-500/30'
          : 'bg-slate-800/50 border-slate-700'
      }`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-slate-400">HIL Status</div>
            <div className="text-xl font-semibold">
              {hilOpen ? 'Waiting on HIL Approval' : 'No Pending HIL Task'}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-slate-400">Current Step</div>
            <div className="text-xl font-semibold">
              {currentStep || '?'}
            </div>
          </div>
        </div>
      </div>

      {/* Violations */}
      {violations.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3 text-red-400">Step Gate Violations</h2>
          <div className="space-y-2">
            {violations.map((task, idx) => (
              <div
                key={idx}
                className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span className="text-red-400">🚫</span>
                  <span className="font-medium text-red-400">{task.task_type}</span>
                  <span className="text-sm text-slate-400">at Step {task.step}</span>
                </div>
                {task.violation_reason && (
                  <div className="text-sm text-red-300 mt-1">
                    {task.violation_reason}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Task History */}
      <div>
        <h2 className="text-lg font-semibold mb-3">HIL Task History</h2>
        {tasks.length === 0 ? (
          <div className="text-slate-400 text-sm">No HIL tasks recorded yet.</div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task, idx) => (
              <div
                key={idx}
                className={`border rounded-lg px-4 py-3 ${
                  task.violation
                    ? 'bg-red-500/5 border-red-500/20'
                    : task.action === 'approved'
                    ? 'bg-green-500/5 border-green-500/20'
                    : task.action === 'rejected'
                    ? 'bg-red-500/5 border-red-500/20'
                    : 'bg-slate-800/50 border-slate-700'
                }`}
              >
                <div className="flex items-center gap-4">
                  <span className="text-xs text-slate-500 font-mono">
                    {formatTime(task.ts)}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                    Step {task.step}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    task.task_type === 'date_confirm'
                      ? 'bg-blue-500/20 text-blue-400'
                      : task.task_type === 'room_approve'
                      ? 'bg-purple-500/20 text-purple-400'
                      : task.task_type === 'offer_review'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-slate-700 text-slate-300'
                  }`}>
                    {task.task_type}
                  </span>
                  <span className={`text-sm font-medium ${
                    task.action === 'approved'
                      ? 'text-green-400'
                      : task.action === 'rejected'
                      ? 'text-red-400'
                      : task.action === 'created'
                      ? 'text-yellow-400'
                      : 'text-slate-300'
                  }`}>
                    {task.action}
                  </span>
                  {task.violation && (
                    <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400">
                      VIOLATION
                    </span>
                  )}
                </div>
                {task.payload_keys && task.payload_keys.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="text-xs text-slate-500">Payload fields:</span>
                    {task.payload_keys.map((key, kidx) => (
                      <span
                        key={kidx}
                        className="text-xs px-1.5 py-0.5 rounded bg-slate-800 text-slate-400"
                      >
                        {key}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Step Requirements Reference */}
      <div className="bg-slate-800/30 border border-slate-700 rounded-lg p-4">
        <h3 className="font-medium text-slate-300 mb-2">Step Requirements</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
          {Object.entries(STEP_REQUIREMENTS).map(([task, minStep]) => (
            <div key={task} className="flex justify-between">
              <span className="text-slate-400">{task}</span>
              <span className="text-slate-300">≥ Step {minStep}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function extractHILTasks(trace: RawTraceEvent[], currentStep: number | null): HILTask[] {
  const tasks: HILTask[] = [];

  trace.forEach((event) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};

    // Look for HIL-related events
    if (
      kind.includes('HIL') ||
      kind.includes('APPROVAL') ||
      (event.subject || '').toLowerCase().includes('hil')
    ) {
      const taskType = (data.task_type as string) ||
        (data.hil_type as string) ||
        inferTaskType(event.subject || '', kind);

      const action = (data.action as string) ||
        (kind.includes('APPROVED') ? 'approved' :
         kind.includes('REJECTED') ? 'rejected' :
         kind.includes('CREATED') ? 'created' : 'unknown');

      const step = event.step || event.owner_step || '';
      const stepNum = parseInt(step.replace(/\D/g, ''), 10) || 0;

      // Check for step gate violation
      const minStep = STEP_REQUIREMENTS[taskType] || 0;
      const violation = minStep > 0 && stepNum < minStep;

      tasks.push({
        ts: event.ts || 0,
        task_type: taskType,
        action,
        step,
        payload_keys: data.payload ? Object.keys(data.payload as object) : undefined,
        violation,
        violation_reason: violation
          ? `${taskType} requires Step ${minStep}+, but created at Step ${stepNum}`
          : undefined,
      });
    }

    // Also look for draft events with HIL approval
    if (kind === 'DRAFT_SEND') {
      const waitState = data.footer && (data.footer as Record<string, unknown>).state;
      if (waitState === 'Waiting on HIL') {
        tasks.push({
          ts: event.ts || 0,
          task_type: 'draft_approval',
          action: 'created',
          step: event.step || event.owner_step || '',
        });
      }
    }
  });

  return tasks.reverse(); // Most recent first
}

function inferTaskType(subject: string, kind: string): string {
  const lower = (subject + kind).toLowerCase();
  if (lower.includes('date')) return 'date_confirm';
  if (lower.includes('room')) return 'room_approve';
  if (lower.includes('offer')) return 'offer_review';
  if (lower.includes('deposit')) return 'deposit_request';
  return 'unknown';
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

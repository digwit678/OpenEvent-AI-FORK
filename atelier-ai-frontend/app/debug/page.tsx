'use client';

import { Suspense, useEffect, useState, useMemo } from 'react';
import ThreadSelector, { useThreadId } from '../components/debug/ThreadSelector';
import NavCard from '../components/debug/NavCard';
import StatusBadges from '../components/debug/StatusBadges';
import ProblemBanner, { detectProblems, Problem } from '../components/debug/ProblemBanner';

interface TraceSummary {
  current_step_major?: number;
  wait_state?: string | null;
  hil_open?: boolean;
}

interface SignalSummary {
  date?: { confirmed?: boolean; value?: string | null };
  room_status?: string | null;
  room_status_display?: string | null;
  requirements_match?: boolean;
  offer_status?: string | null;
  offer_status_display?: string | null;
  wait_state?: string | null;
}

interface TraceResponse {
  thread_id: string;
  state: Record<string, unknown>;
  confirmed?: SignalSummary;
  summary?: TraceSummary;
}

const STEP_NAMES: Record<number, string> = {
  1: 'Intake',
  2: 'Date Confirmation',
  3: 'Room Availability',
  4: 'Offer',
  5: 'Negotiation',
  6: 'Transition',
  7: 'Confirmation',
};

function DebugLandingContent() {
  const threadId = useThreadId();
  const [state, setState] = useState<Record<string, unknown>>({});
  const [signals, setSignals] = useState<SignalSummary | undefined>();
  const [summary, setSummary] = useState<TraceSummary | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [dismissedProblems, setDismissedProblems] = useState<Set<string>>(new Set());

  // Fetch trace data
  useEffect(() => {
    if (!threadId) {
      setState({});
      setSignals(undefined);
      setSummary(undefined);
      return;
    }

    const controller = new AbortController();
    const fetchTrace = async () => {
      try {
        const response = await fetch(
          `/api/debug/threads/${encodeURIComponent(threadId)}?granularity=logic`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          if (response.status === 404) {
            setError('Thread not found or tracing disabled');
            return;
          }
          throw new Error(await response.text());
        }
        const payload = (await response.json()) as TraceResponse;
        setState(payload.state || {});
        setSignals(payload.confirmed);
        setSummary(payload.summary);
        setError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      }
    };

    fetchTrace();
    const interval = setInterval(fetchTrace, 2000);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [threadId]);

  // Compute status badges
  const statusBadges = useMemo(() => {
    const stepNum = summary?.current_step_major;
    const stepName = stepNum ? STEP_NAMES[stepNum] || `Step ${stepNum}` : 'Unknown';

    return [
      {
        label: 'Current Step',
        value: stepNum ? `${stepNum}. ${stepName}` : 'Waiting...',
        tone: stepNum ? 'ok' : 'pending',
      },
      {
        label: 'Date',
        value: signals?.date?.confirmed
          ? `Confirmed ${signals.date.value ? `(${signals.date.value})` : ''}`
          : 'Pending',
        tone: signals?.date?.confirmed ? 'ok' : 'pending',
      },
      {
        label: 'Room',
        value: signals?.room_status_display || signals?.room_status || 'Unselected',
        tone:
          (signals?.room_status_display || '').toLowerCase().includes('available') ||
          (signals?.room_status_display || '').toLowerCase().includes('locked')
            ? 'ok'
            : (signals?.room_status_display || '').toLowerCase().includes('unavailable')
            ? 'warn'
            : 'pending',
      },
      {
        label: 'Hash',
        value: signals?.requirements_match ? 'Match' : signals?.requirements_match === false ? 'Mismatch' : 'N/A',
        tone: signals?.requirements_match ? 'ok' : signals?.requirements_match === false ? 'error' : 'muted',
      },
      {
        label: 'Offer',
        value: signals?.offer_status_display || 'Not started',
        tone:
          (signals?.offer_status_display || '').toLowerCase().includes('confirmed')
            ? 'ok'
            : (signals?.offer_status_display || '').toLowerCase().includes('waiting')
            ? 'warn'
            : 'pending',
      },
      {
        label: 'State',
        value: summary?.wait_state || signals?.wait_state || 'Unknown',
        tone: summary?.hil_open ? 'warn' : 'ok',
      },
    ] as const;
  }, [signals, summary]);

  // Detect problems
  const problems = useMemo(() => {
    const detected = detectProblems(state);
    return detected.filter((p) => !dismissedProblems.has(p.id));
  }, [state, dismissedProblems]);

  const handleDismissProblem = (id: string) => {
    setDismissedProblems((prev) => new Set([...prev, id]));
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-3xl font-bold">OpenEvent Debugger</h1>
            <p className="text-sm text-slate-400 mt-1">
              Workflow debugging dashboard - select a view below to dive deeper
            </p>
          </div>
          <ThreadSelector />
        </header>

        {/* Error state */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg">
            {error}
          </div>
        )}

        {/* Problem Banner */}
        {problems.length > 0 && (
          <ProblemBanner
            problems={problems}
            threadId={threadId}
            onDismiss={handleDismissProblem}
          />
        )}

        {/* Status Badges */}
        {threadId && <StatusBadges badges={statusBadges as any} />}

        {/* No thread connected */}
        {!threadId && (
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-8 text-center">
            <p className="text-slate-400">
              No thread connected. Start a chat session or enter a thread ID above.
            </p>
          </div>
        )}

        {/* Navigation Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <NavCard
            href="/debug/detection"
            title="Detection"
            icon="🔍"
            description="View intent classification, entity extraction, and pattern matching results"
            threadId={threadId}
            badge={problems.some((p) => p.type === 'classification_conflict') ? { text: 'Issue', tone: 'warn' } : undefined}
          />
          <NavCard
            href="/debug/agents"
            title="Agents &amp; Prompts"
            icon="🤖"
            description="See LLM prompts, responses, and agent behavior throughout the workflow"
            threadId={threadId}
          />
          <NavCard
            href="/debug/errors"
            title="Errors &amp; Alerts"
            icon="⚠️"
            description="Auto-detected problems, hash mismatches, detour loops, and LLM diagnosis"
            threadId={threadId}
            badge={problems.length > 0 ? { text: `${problems.length} issue${problems.length > 1 ? 's' : ''}`, tone: 'error' } : undefined}
          />
          <NavCard
            href="/debug/timeline"
            title="Timeline"
            icon="⏱️"
            description="Full event timeline with step tracking, gates, and state snapshots"
            threadId={threadId}
          />
          <NavCard
            href="/debug/dates"
            title="Date Audit"
            icon="📅"
            description="Track date values through every transformation and parsing step"
            threadId={threadId}
            badge={problems.some((p) => p.type === 'date_inconsistency') ? { text: 'Mismatch', tone: 'error' } : undefined}
          />
          <NavCard
            href="/debug/hil"
            title="HIL Tasks"
            icon="👤"
            description="Human-in-the-loop task status, approvals, and step gating"
            threadId={threadId}
            badge={problems.some((p) => p.type === 'hil_violation') ? { text: 'Violation', tone: 'warn' } : undefined}
          />
        </div>

        {/* Quick Actions */}
        <div className="flex flex-wrap gap-3 pt-4 border-t border-slate-800">
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/llm-diagnosis` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              threadId
                ? 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed'
            }`}
          >
            Copy LLM Diagnosis
          </a>
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/download` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              threadId
                ? 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed'
            }`}
          >
            Download JSON
          </a>
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/text` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              threadId
                ? 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed'
            }`}
          >
            Download Text
          </a>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs text-slate-500 pt-4">
          OpenEvent Debugger v2.0 - Landing Page Architecture
        </footer>
      </div>
    </div>
  );
}

export default function DebugLandingPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading debugger...</div>
      </div>
    }>
      <DebugLandingContent />
    </Suspense>
  );
}

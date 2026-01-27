'use client';

import { Suspense, useEffect, useState, useMemo } from 'react';
import ThreadSelector, { useThreadId } from '../components/debug/ThreadSelector';
import NavCard from '../components/debug/NavCard';
import StatusBadges from '../components/debug/StatusBadges';
import ProblemBanner, { detectProblems, Problem } from '../components/debug/ProblemBanner';
import QuickDiagnosis from '../components/debug/QuickDiagnosis';
import CancelEventButton from '../components/CancelEventButton';

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

  // Extract event_id from state for cancellation button
  const eventId = useMemo(() => {
    return (state.event_id as string) || (state.eventId as string) || null;
  }, [state]);

  // Check if site visit is scheduled (step >= 7 or flag set)
  const hasSiteVisit = useMemo(() => {
    const step = summary?.current_step_major;
    const siteVisitFlag = state.site_visit_scheduled as boolean;
    return (step && step >= 7) || siteVisitFlag || false;
  }, [summary, state]);

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

  const statusBadges = useMemo(() => {
    const stepNum = summary?.current_step_major;
    const stepName = stepNum ? STEP_NAMES[stepNum] || `Step ${stepNum}` : 'Unknown';

    return [
      {
        label: 'Step',
        value: stepNum ? `${stepNum}. ${stepName}` : 'Waiting...',
        tone: stepNum ? 'ok' : 'pending',
      },
      {
        label: 'Date',
        value: signals?.date?.confirmed ? `${signals.date.value || 'Confirmed'}` : 'Pending',
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

  const problems = useMemo(() => {
    const detected = detectProblems(state);
    return detected.filter((p) => !dismissedProblems.has(p.id));
  }, [state, dismissedProblems]);

  const handleDismissProblem = (id: string) => {
    setDismissedProblems((prev) => new Set([...prev, id]));
  };

  return (
    <div
      className="min-h-screen bg-slate-900 text-slate-100 p-8 debug-page"
      style={{
        backgroundColor: '#0f172a',
        color: '#f1f5f9',
        padding: '32px',
        minHeight: '100vh',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
      }}
    >
      <div className="max-w-6xl mx-auto space-y-8" style={{ maxWidth: '72rem', margin: '0 auto' }}>
        {/* Header */}
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1
              className="text-4xl font-bold"
              style={{ fontSize: '36px', fontWeight: '700', color: '#f1f5f9', letterSpacing: '-0.025em' }}
            >
              OpenEvent Debugger
            </h1>
            <p
              className="text-base text-slate-400 mt-2"
              style={{ fontSize: '16px', color: '#94a3b8', marginTop: '8px' }}
            >
              Workflow analysis &amp; debugging dashboard
            </p>
          </div>
          <ThreadSelector />
        </header>

        {/* Error state */}
        {error && (
          <div
            className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg"
            style={{ backgroundColor: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171', padding: '12px 16px', borderRadius: '8px' }}
          >
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
          <div
            className="bg-slate-800/50 border border-slate-700 rounded-xl p-8 text-center"
            style={{ backgroundColor: 'rgba(30,41,59,0.5)', border: '1px solid #334155', borderRadius: '12px', padding: '32px', textAlign: 'center' }}
          >
            <p className="text-slate-400" style={{ color: '#94a3b8' }}>
              No thread connected. Start a chat session or enter a thread ID above.
            </p>
          </div>
        )}

        {/* Quick Diagnosis */}
        {threadId && (
          <QuickDiagnosis
            threadId={threadId}
            currentStep={summary?.current_step_major}
          />
        )}

        {/* Navigation Cards */}
        <div>
          <h2
            className="text-xl font-semibold text-slate-200 mb-5"
            style={{ fontSize: '20px', fontWeight: '600', color: '#e2e8f0', marginBottom: '20px' }}
          >
            Debug Views
          </h2>
          <div
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"
            style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}
          >
            <NavCard
              href="/debug/detection"
              title="Detection"
              icon="🔍"
              description="Intent classification, entity extraction, and pattern matching"
              threadId={threadId}
              badge={problems.some((p) => p.type === 'classification_conflict') ? { text: 'Issue', tone: 'warn' } : undefined}
            />
            <NavCard
              href="/debug/agents"
              title="Agents"
              icon="🤖"
              description="LLM prompts, responses, extractions, and DB operations"
              threadId={threadId}
            />
            <NavCard
              href="/debug/errors"
              title="Errors"
              icon="⚠️"
              description="Auto-detected problems, hash mismatches, and LLM diagnosis"
              threadId={threadId}
              badge={problems.length > 0 ? { text: `${problems.length}`, tone: 'error' } : undefined}
            />
            <NavCard
              href="/debug/timeline"
              title="Timeline"
              icon="⏱️"
              description="Full event timeline with step tracking and state snapshots"
              threadId={threadId}
            />
            <NavCard
              href="/debug/dates"
              title="Dates"
              icon="📅"
              description="Date values through every transformation and parsing step"
              threadId={threadId}
              badge={problems.some((p) => p.type === 'date_inconsistency') ? { text: 'Mismatch', tone: 'error' } : undefined}
            />
            <NavCard
              href="/debug/hil"
              title="HIL"
              icon="👤"
              description="Human-in-the-loop tasks, approvals, and step gating"
              threadId={threadId}
              badge={problems.some((p) => p.type === 'hil_violation') ? { text: 'Alert', tone: 'warn' } : undefined}
            />
          </div>
        </div>

        {/* Quick Actions */}
        <div
          className="flex flex-wrap gap-3 pt-4 border-t border-slate-800"
          style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', paddingTop: '16px', borderTop: '1px solid #1e293b' }}
        >
          {/* Cancel Event Button */}
          {eventId && (
            <CancelEventButton
              eventId={eventId}
              hasSiteVisit={hasSiteVisit}
              currentStep={summary?.current_step_major}
              darkTheme={true}
              onCancel={(result) => {
                console.log('Event cancelled:', result);
                // Could add a toast notification here
              }}
            />
          )}
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/llm-diagnosis` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              threadId
                ? 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed'
            }`}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              backgroundColor: threadId ? 'rgba(168,85,247,0.2)' : '#1e293b',
              color: threadId ? '#c084fc' : '#64748b',
              textDecoration: 'none',
            }}
          >
            Copy LLM Diagnosis
          </a>
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/download` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              backgroundColor: threadId ? '#334155' : '#1e293b',
              color: threadId ? '#cbd5e1' : '#64748b',
              textDecoration: 'none',
            }}
          >
            Download JSON
          </a>
          <a
            href={threadId ? `/api/debug/threads/${encodeURIComponent(threadId)}/timeline/text` : '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              backgroundColor: threadId ? '#334155' : '#1e293b',
              color: threadId ? '#cbd5e1' : '#64748b',
              textDecoration: 'none',
            }}
          >
            Download Text
          </a>
        </div>

        {/* Footer */}
        <footer
          className="text-center text-xs text-slate-500 pt-4"
          style={{ textAlign: 'center', fontSize: '12px', color: '#64748b', paddingTop: '16px' }}
        >
          OpenEvent Debugger v2.0
        </footer>
      </div>
    </div>
  );
}

export default function DebugLandingPage() {
  return (
    <Suspense fallback={
      <div
        className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center"
        style={{ backgroundColor: '#0f172a', color: '#f1f5f9', padding: '24px', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div style={{ color: '#94a3b8' }}>Loading debugger...</div>
      </div>
    }>
      <DebugLandingContent />
    </Suspense>
  );
}

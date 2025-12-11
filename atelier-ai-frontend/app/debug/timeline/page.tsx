'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { DebugLayout } from '../../components/debug/DebugHeader';
import DebugPanel from '../../components/DebugPanel';

// Timeline icon
function TimelineIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function TimelinePageContent() {
  const searchParams = useSearchParams();
  const queryThreadId = searchParams.get('thread') || '';
  const [threadId, setThreadId] = useState<string>(queryThreadId);
  const [manualId, setManualId] = useState<string>(queryThreadId);

  useEffect(() => {
    if (queryThreadId) {
      setThreadId(queryThreadId);
      setManualId(queryThreadId);
      return;
    }
    try {
      const stored = localStorage.getItem('lastThreadId');
      if (stored) {
        setThreadId(stored);
        setManualId(stored);
      }
    } catch {
      // ignore storage errors
    }
  }, [queryThreadId]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === 'lastThreadId' && event.newValue) {
        setThreadId(event.newValue);
        setManualId(event.newValue);
      }
    };
    window.addEventListener('storage', handleStorage);
    const interval = window.setInterval(() => {
      try {
        const stored = localStorage.getItem('lastThreadId');
        if (stored && stored !== threadId) {
          setThreadId(stored);
          setManualId(stored);
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.clearInterval(interval);
    };
  }, [threadId]);

  const effectiveThreadId = useMemo(() => threadId || manualId || null, [threadId, manualId]);

  // Custom header content for inline thread input
  const headerContent = (
    <div className="flex items-center gap-2">
      <input
        value={manualId}
        onChange={(event) => setManualId(event.target.value)}
        placeholder="Enter thread ID..."
        className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50 w-48"
      />
      <button
        type="button"
        onClick={() => setThreadId(manualId)}
        className="px-4 py-2 text-sm bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/30 rounded-lg text-cyan-400 font-medium transition-colors"
      >
        Attach
      </button>
    </div>
  );

  return (
    <DebugLayout
      title="Timeline View"
      icon={<TimelineIcon />}
      headerContent={headerContent}
    >
      <div className="space-y-6">
        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl overflow-hidden">
          <DebugPanel threadId={effectiveThreadId} pollMs={1500} />
        </div>

        {/* Info card */}
        <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-cyan-500/20 text-cyan-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
            </div>
            <div>
              <h3 className="font-medium text-cyan-400 mb-2">Timeline View Guide</h3>
              <ul className="text-sm text-slate-300 space-y-1.5">
                <li className="flex items-start gap-2">
                  <span className="text-cyan-400 mt-0.5">*</span>
                  <span>Shows full event timeline with step tracking, gates, and state snapshots</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-cyan-400 mt-0.5">*</span>
                  <span>Auto-refreshes every 1.5 seconds while connected</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-cyan-400 mt-0.5">*</span>
                  <span>Click events to expand and see full details</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function TimelinePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading timeline view...</span>
        </div>
      </div>
    }>
      <TimelinePageContent />
    </Suspense>
  );
}

'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import DebugPanel from '../../components/DebugPanel';

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

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-4">
      <div className="max-w-6xl mx-auto space-y-4">
        <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={effectiveThreadId ? `/debug?thread=${encodeURIComponent(effectiveThreadId)}` : '/debug'}
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              &larr; Back to Dashboard
            </Link>
            <div>
              <h1 className="text-2xl font-bold">Timeline View</h1>
              <p className="text-sm text-slate-300 mt-1">
                Full event timeline with step tracking, gates, and state snapshots
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={manualId}
              onChange={(event) => setManualId(event.target.value)}
              placeholder="thread id"
              className="bg-slate-800 border border-slate-700 rounded px-3 py-1 text-sm focus:outline-none focus:ring focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => setThreadId(manualId)}
              className="px-3 py-1 text-sm bg-blue-500 hover:bg-blue-600 rounded text-white"
            >
              Attach
            </button>
          </div>
        </header>
        <div className="border border-slate-700 rounded-2xl overflow-hidden shadow-xl bg-slate-950/60">
          <DebugPanel threadId={effectiveThreadId} pollMs={1500} />
        </div>
      </div>
    </div>
  );
}

export default function TimelinePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-4 flex items-center justify-center">
        <div className="text-slate-400">Loading timeline view...</div>
      </div>
    }>
      <TimelinePageContent />
    </Suspense>
  );
}

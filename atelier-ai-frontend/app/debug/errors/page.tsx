'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useThreadId } from '../../components/debug/ThreadSelector';
import ThreadSelector from '../../components/debug/ThreadSelector';
import ErrorsView from '../../components/debug/ErrorsView';

function ErrorsPageContent() {
  const threadId = useThreadId();

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={threadId ? `/debug?thread=${encodeURIComponent(threadId)}` : '/debug'}
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              &larr; Back
            </Link>
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2">
                <span>⚠️</span> Errors &amp; Alerts
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Auto-detected problems, hash mismatches, detour loops, and diagnostics
              </p>
            </div>
          </div>
          <ThreadSelector />
        </header>

        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6">
          <ErrorsView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <h3 className="font-medium text-red-400 mb-2">Problem Types</h3>
          <ul className="text-sm text-slate-300 space-y-1">
            <li><strong>⚠ Hash Mismatch</strong> - requirements_hash != room_eval_hash (room needs re-evaluation)</li>
            <li><strong>↻ Detour Loop</strong> - Same step pair triggered &gt;2 times</li>
            <li><strong>⏸ Stuck State</strong> - No events for extended period</li>
            <li><strong>📅 Date Inconsistency</strong> - Parsed date differs from stored date</li>
            <li><strong>🚫 HIL Violation</strong> - HIL task created at wrong step</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function ErrorsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading errors view...</div>
      </div>
    }>
      <ErrorsPageContent />
    </Suspense>
  );
}

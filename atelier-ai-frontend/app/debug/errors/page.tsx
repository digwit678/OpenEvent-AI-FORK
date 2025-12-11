'use client';

import { Suspense } from 'react';
import { useThreadId } from '../../components/debug/ThreadSelector';
import { DebugLayout } from '../../components/debug/DebugHeader';
import ErrorsView from '../../components/debug/ErrorsView';

// Error icon
function ErrorIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  );
}

function ErrorsPageContent() {
  const threadId = useThreadId();

  return (
    <DebugLayout
      title="Errors & Alerts"
      icon={<ErrorIcon />}
    >
      <div className="space-y-6">
        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
          <ErrorsView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-rose-500/20 text-rose-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0 3.75h.007v.008H12v-.008zm0 0h-.007v.008H12v-.008zm-9.303-.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
              </svg>
            </div>
            <div>
              <h3 className="font-medium text-rose-400 mb-2">Problem Types</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-slate-300">
                <div className="flex items-center gap-2">
                  <span className="text-amber-400">!</span>
                  <span><strong className="text-slate-200">Hash Mismatch</strong> - Room needs re-evaluation</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-amber-400">@</span>
                  <span><strong className="text-slate-200">Detour Loop</strong> - Same step triggered &gt;2x</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">||</span>
                  <span><strong className="text-slate-200">Stuck State</strong> - No events for extended period</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-amber-400">#</span>
                  <span><strong className="text-slate-200">Date Inconsistency</strong> - Parsed != stored</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-rose-400">X</span>
                  <span><strong className="text-slate-200">HIL Violation</strong> - Wrong step gate</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function ErrorsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-rose-500/30 border-t-rose-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading errors view...</span>
        </div>
      </div>
    }>
      <ErrorsPageContent />
    </Suspense>
  );
}

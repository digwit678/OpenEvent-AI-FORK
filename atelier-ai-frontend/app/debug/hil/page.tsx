'use client';

import { Suspense } from 'react';
import { useThreadId } from '../../components/debug/ThreadSelector';
import { DebugLayout } from '../../components/debug/DebugHeader';
import HILView from '../../components/debug/HILView';

// HIL icon
function HILIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
    </svg>
  );
}

function HILPageContent() {
  const threadId = useThreadId();

  return (
    <DebugLayout
      title="HIL Task Tracking"
      icon={<HILIcon />}
    >
      <div className="space-y-6">
        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
          <HILView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-emerald-500/20 text-emerald-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
            </div>
            <div>
              <h3 className="font-medium text-emerald-400 mb-2">HIL (Human-in-the-Loop) Gates</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-slate-300">
                <div>
                  <strong className="text-slate-200">date_confirm</strong> - Manager approves date options
                </div>
                <div>
                  <strong className="text-slate-200">room_approve</strong> - Manager confirms room
                </div>
                <div>
                  <strong className="text-slate-200">offer_review</strong> - Manager reviews offer
                </div>
                <div>
                  <strong className="text-slate-200">deposit_request</strong> - Manager approves deposit
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Known Issue Reference */}
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10 text-amber-500">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <div>
              <h3 className="font-medium text-amber-500 mb-1">Known Issue: Field Name Mismatches</h3>
              <p className="text-sm text-slate-400">
                Some HIL task payloads use inconsistent field names (e.g., draft_msg vs draft_body).
                Check the "Payload fields" section to verify field names match frontend expectations.
              </p>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function HILPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading HIL view...</span>
        </div>
      </div>
    }>
      <HILPageContent />
    </Suspense>
  );
}

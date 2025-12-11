'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useThreadId } from '../../components/debug/ThreadSelector';
import ThreadSelector from '../../components/debug/ThreadSelector';
import HILView from '../../components/debug/HILView';

function HILPageContent() {
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
                <span>👤</span> HIL Task Tracking
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Human-in-the-loop task status, approvals, and step gating
              </p>
            </div>
          </div>
          <ThreadSelector />
        </header>

        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6">
          <HILView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-teal-500/10 border border-teal-500/30 rounded-lg p-4">
          <h3 className="font-medium text-teal-400 mb-2">HIL (Human-in-the-Loop) Gates</h3>
          <ul className="text-sm text-slate-300 space-y-1">
            <li><strong>date_confirm</strong> - Manager approves date options before sending to client</li>
            <li><strong>room_approve</strong> - Manager confirms room selection</li>
            <li><strong>offer_review</strong> - Manager reviews offer before sending</li>
            <li><strong>deposit_request</strong> - Manager approves deposit request</li>
          </ul>
        </div>

        {/* Known Issue Reference */}
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
          <h3 className="font-medium text-yellow-400 mb-2">Known Issue: Field Name Mismatches</h3>
          <p className="text-sm text-slate-300">
            Some HIL task payloads use inconsistent field names (e.g., draft_msg vs draft_body).
            Check the "Payload fields" section to verify field names match frontend expectations.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function HILPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading HIL view...</div>
      </div>
    }>
      <HILPageContent />
    </Suspense>
  );
}

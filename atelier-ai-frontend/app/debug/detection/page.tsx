'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useThreadId } from '../../components/debug/ThreadSelector';
import ThreadSelector from '../../components/debug/ThreadSelector';
import DetectionView from '../../components/debug/DetectionView';

function DetectionPageContent() {
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
                <span>🔍</span> Detection View
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Intent classification, entity extraction, and pattern matching
              </p>
            </div>
          </div>
          <ThreadSelector />
        </header>

        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6">
          <DetectionView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
          <h3 className="font-medium text-blue-400 mb-2">How to read this view</h3>
          <ul className="text-sm text-slate-300 space-y-1">
            <li><strong>Click any row</strong> to expand and see full details</li>
            <li><strong>Matched Patterns</strong> show which keywords/regex triggered the classification</li>
            <li><strong>Alternatives</strong> show other classifications that were considered</li>
            <li><strong>Confidence</strong> percentage indicates LLM certainty (when available)</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function DetectionPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading detection view...</div>
      </div>
    }>
      <DetectionPageContent />
    </Suspense>
  );
}

'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useThreadId } from '../../components/debug/ThreadSelector';
import ThreadSelector from '../../components/debug/ThreadSelector';
import DateTrailView from '../../components/debug/DateTrailView';

function DatesPageContent() {
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
                <span>📅</span> Date Audit Trail
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Track date values through every transformation and parsing step
              </p>
            </div>
          </div>
          <ThreadSelector />
        </header>

        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6">
          <DateTrailView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
          <h3 className="font-medium text-blue-400 mb-2">Date Processing Pipeline</h3>
          <ul className="text-sm text-slate-300 space-y-1">
            <li><strong>Raw Input</strong> - The original text from the client message</li>
            <li><strong>Parsed Value</strong> - Date extracted using Regex/NER/LLM</li>
            <li><strong>Stored Value</strong> - Final value saved to database</li>
            <li><strong>Parser Used</strong> - Which method extracted the date</li>
            <li><strong>MISMATCH</strong> - Red flag when values differ unexpectedly</li>
          </ul>
        </div>

        {/* Known Issue Reference */}
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
          <h3 className="font-medium text-yellow-400 mb-2">Known Issue: Date Mismatch Bug</h3>
          <p className="text-sm text-slate-300">
            There is a known open bug where dates like "February 7th" may be stored as "2026-02-20".
            This view helps trace exactly where the mismatch occurs in the pipeline.
            See TEAM_GUIDE.md for more details.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function DatesPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading date audit view...</div>
      </div>
    }>
      <DatesPageContent />
    </Suspense>
  );
}

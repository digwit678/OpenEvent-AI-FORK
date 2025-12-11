'use client';

import { Suspense } from 'react';
import { useThreadId } from '../../components/debug/ThreadSelector';
import { DebugLayout } from '../../components/debug/DebugHeader';
import DateTrailView from '../../components/debug/DateTrailView';

// Date icon
function DateIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  );
}

function DatesPageContent() {
  const threadId = useThreadId();

  return (
    <DebugLayout
      title="Date Audit Trail"
      icon={<DateIcon />}
    >
      <div className="space-y-6">
        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
          <DateTrailView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
            </div>
            <div>
              <h3 className="font-medium text-amber-400 mb-2">Date Processing Pipeline</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-slate-300">
                <div>
                  <strong className="text-slate-200">Raw Input</strong> - Original text from client
                </div>
                <div>
                  <strong className="text-slate-200">Parsed Value</strong> - Extracted via Regex/NER/LLM
                </div>
                <div>
                  <strong className="text-slate-200">Stored Value</strong> - Final value in database
                </div>
                <div>
                  <strong className="text-slate-200">Parser Used</strong> - Extraction method
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
              <h3 className="font-medium text-amber-500 mb-1">Known Issue: Date Mismatch Bug</h3>
              <p className="text-sm text-slate-400">
                There is a known open bug where dates like "February 7th" may be stored as "2026-02-20".
                This view helps trace exactly where the mismatch occurs in the pipeline.
                See TEAM_GUIDE.md for more details.
              </p>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function DatesPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading date audit view...</span>
        </div>
      </div>
    }>
      <DatesPageContent />
    </Suspense>
  );
}

'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useThreadId } from '../../components/debug/ThreadSelector';
import ThreadSelector from '../../components/debug/ThreadSelector';
import AgentView from '../../components/debug/AgentView';

function AgentsPageContent() {
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
                <span>🤖</span> Agents &amp; Prompts
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                LLM prompts, responses, and agent behavior throughout the workflow
              </p>
            </div>
          </div>
          <ThreadSelector />
        </header>

        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-6">
          <AgentView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4">
          <h3 className="font-medium text-purple-400 mb-2">Understanding Agent Prompts</h3>
          <ul className="text-sm text-slate-300 space-y-1">
            <li><strong>Blue rows (\u2192 Prompt)</strong> - Instructions sent to the LLM</li>
            <li><strong>Green rows (\u2190 Response)</strong> - LLM output received</li>
            <li><strong>Structured Outputs</strong> - Parsed data extracted from responses</li>
            <li>Email addresses and phone numbers are masked for privacy</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 text-slate-100 p-6 flex items-center justify-center">
        <div className="text-slate-400">Loading agents view...</div>
      </div>
    }>
      <AgentsPageContent />
    </Suspense>
  );
}

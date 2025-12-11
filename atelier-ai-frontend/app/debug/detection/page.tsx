'use client';

import { Suspense } from 'react';
import { useThreadId } from '../../components/debug/ThreadSelector';
import { DebugLayout } from '../../components/debug/DebugHeader';
import DetectionView from '../../components/debug/DetectionView';

// Detection icon
function DetectionIcon() {
  return (
    <svg style={{ width: '24px', height: '24px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function DetectionPageContent() {
  const threadId = useThreadId();

  return (
    <DebugLayout
      title="Detection View"
      icon={<DetectionIcon />}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {/* Main content */}
        <div style={{
          backgroundColor: 'rgba(30,41,59,0.3)',
          border: '1px solid rgba(51,65,85,0.5)',
          borderRadius: '16px',
          padding: '24px'
        }}>
          <DetectionView threadId={threadId} />
        </div>

        {/* Info card */}
        <div style={{
          backgroundColor: 'rgba(59,130,246,0.1)',
          border: '1px solid rgba(59,130,246,0.3)',
          borderRadius: '14px',
          padding: '20px 24px'
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
            <div style={{ padding: '10px', borderRadius: '10px', backgroundColor: 'rgba(59,130,246,0.2)', color: '#60a5fa' }}>
              <svg style={{ width: '22px', height: '22px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
            </div>
            <div>
              <h3 style={{ fontWeight: '600', color: '#60a5fa', marginBottom: '12px', fontSize: '16px' }}>How to read this view</h3>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <li style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '15px', color: '#cbd5e1' }}>
                  <span style={{ color: '#60a5fa', marginTop: '2px' }}>•</span>
                  <span><strong style={{ color: '#e2e8f0' }}>Click any row</strong> to expand and see full details</span>
                </li>
                <li style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '15px', color: '#cbd5e1' }}>
                  <span style={{ color: '#60a5fa', marginTop: '2px' }}>•</span>
                  <span><strong style={{ color: '#e2e8f0' }}>Matched Patterns</strong> show which keywords/regex triggered the classification</span>
                </li>
                <li style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '15px', color: '#cbd5e1' }}>
                  <span style={{ color: '#60a5fa', marginTop: '2px' }}>•</span>
                  <span><strong style={{ color: '#e2e8f0' }}>Alternatives</strong> show other classifications that were considered</span>
                </li>
                <li style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '15px', color: '#cbd5e1' }}>
                  <span style={{ color: '#60a5fa', marginTop: '2px' }}>•</span>
                  <span><strong style={{ color: '#e2e8f0' }}>Confidence</strong> percentage indicates LLM certainty (when available)</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function DetectionPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading detection view...</span>
        </div>
      </div>
    }>
      <DetectionPageContent />
    </Suspense>
  );
}

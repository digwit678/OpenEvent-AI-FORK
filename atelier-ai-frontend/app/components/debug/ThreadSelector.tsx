'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

interface ThreadSelectorProps {
  onThreadChange?: (threadId: string | null) => void;
  className?: string;
}

function LinkIcon() {
  return (
    <svg style={{ width: '16px', height: '16px' }} className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg style={{ width: '14px', height: '14px' }} className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

export default function ThreadSelector({ onThreadChange, className = '' }: ThreadSelectorProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryThreadId = searchParams.get('thread') || '';
  const [threadId, setThreadId] = useState<string>(queryThreadId);
  const [manualId, setManualId] = useState<string>(queryThreadId);

  // Sync from query param or localStorage
  useEffect(() => {
    if (queryThreadId) {
      setThreadId(queryThreadId);
      setManualId(queryThreadId);
      onThreadChange?.(queryThreadId);
      return;
    }
    try {
      const stored = localStorage.getItem('lastThreadId');
      if (stored) {
        setThreadId(stored);
        setManualId(stored);
        onThreadChange?.(stored);
      }
    } catch {
      // ignore storage errors
    }
  }, [queryThreadId, onThreadChange]);

  // Poll for localStorage changes (cross-tab sync)
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === 'lastThreadId' && event.newValue) {
        setThreadId(event.newValue);
        setManualId(event.newValue);
        onThreadChange?.(event.newValue);
      }
    };
    window.addEventListener('storage', handleStorage);

    const interval = window.setInterval(() => {
      try {
        const stored = localStorage.getItem('lastThreadId');
        if (stored && stored !== threadId) {
          setThreadId(stored);
          setManualId(stored);
          onThreadChange?.(stored);
        }
      } catch {
        // ignore
      }
    }, 2000);

    return () => {
      window.removeEventListener('storage', handleStorage);
      window.clearInterval(interval);
    };
  }, [threadId, onThreadChange]);

  const handleAttach = useCallback(() => {
    setThreadId(manualId);
    onThreadChange?.(manualId || null);
    // Update URL with thread param
    if (manualId) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('thread', manualId);
      router.replace(`?${params.toString()}`);
    }
  }, [manualId, onThreadChange, router, searchParams]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }} className={className}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b' }}>
        <LinkIcon />
        <span style={{ fontSize: '14px', fontWeight: '500' }}>Thread</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <input
          value={manualId}
          onChange={(event) => setManualId(event.target.value)}
          placeholder="Enter thread ID..."
          style={{
            backgroundColor: 'rgba(30,41,59,0.5)',
            border: '1px solid #334155',
            borderRadius: '10px 0 0 10px',
            padding: '10px 16px',
            fontSize: '14px',
            color: '#f1f5f9',
            minWidth: '200px',
            outline: 'none'
          }}
        />
        <button
          type="button"
          onClick={handleAttach}
          style={{
            padding: '10px 16px',
            fontSize: '14px',
            fontWeight: '500',
            backgroundColor: 'rgba(139,92,246,0.2)',
            border: '1px solid rgba(139,92,246,0.3)',
            borderLeft: 'none',
            borderRadius: '0 10px 10px 0',
            color: '#a78bfa',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          Attach
        </button>
      </div>
      {threadId && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 12px',
          borderRadius: '8px',
          backgroundColor: 'rgba(34,197,94,0.1)',
          border: '1px solid rgba(34,197,94,0.3)'
        }}>
          <span style={{ color: '#4ade80' }}><CheckIcon /></span>
          <span style={{ fontSize: '13px', fontWeight: '500', color: '#4ade80' }}>Connected</span>
        </div>
      )}
    </div>
  );
}

export function useThreadId(): string | null {
  const searchParams = useSearchParams();
  const queryThreadId = searchParams.get('thread') || '';
  const [threadId, setThreadId] = useState<string | null>(queryThreadId || null);

  useEffect(() => {
    if (queryThreadId) {
      setThreadId(queryThreadId);
      return;
    }
    try {
      const stored = localStorage.getItem('lastThreadId');
      if (stored) {
        setThreadId(stored);
      }
    } catch {
      // ignore
    }
  }, [queryThreadId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      try {
        const stored = localStorage.getItem('lastThreadId');
        if (stored && stored !== threadId) {
          setThreadId(stored);
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => window.clearInterval(interval);
  }, [threadId]);

  return threadId;
}

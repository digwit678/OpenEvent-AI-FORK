'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

interface ThreadSelectorProps {
  onThreadChange?: (threadId: string | null) => void;
  className?: string;
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
    <div className={`flex items-center gap-2 ${className}`}>
      <label className="text-sm text-slate-400">Thread:</label>
      <input
        value={manualId}
        onChange={(event) => setManualId(event.target.value)}
        placeholder="thread id"
        className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring focus:ring-blue-500 min-w-[200px]"
      />
      <button
        type="button"
        onClick={handleAttach}
        className="px-3 py-1.5 text-sm bg-blue-500 hover:bg-blue-600 rounded text-white transition-colors"
      >
        Attach
      </button>
      {threadId && (
        <span className="text-xs text-green-400 ml-2">
          Connected
        </span>
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

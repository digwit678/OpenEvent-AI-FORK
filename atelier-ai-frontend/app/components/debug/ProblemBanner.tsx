'use client';

import Link from 'next/link';

export interface Problem {
  id: string;
  type: 'hash_mismatch' | 'detour_loop' | 'stuck' | 'classification_conflict' | 'date_inconsistency' | 'hil_violation';
  message: string;
  severity: 'error' | 'warn' | 'info';
  link?: string;
}

interface ProblemBannerProps {
  problems: Problem[];
  threadId?: string | null;
  onDismiss?: (problemId: string) => void;
}

const problemIcons: Record<Problem['type'], string> = {
  hash_mismatch: '⚠',
  detour_loop: '↻',
  stuck: '⏸',
  classification_conflict: '❓',
  date_inconsistency: '📅',
  hil_violation: '🚫',
};

export default function ProblemBanner({ problems, threadId, onDismiss }: ProblemBannerProps) {
  if (problems.length === 0) return null;

  const severityColors = {
    error: 'bg-red-500/10 border-red-500/30 text-red-400',
    warn: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
    info: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  };

  return (
    <div className="space-y-2">
      {problems.map((problem) => {
        const linkHref = problem.link
          ? threadId
            ? `${problem.link}?thread=${encodeURIComponent(threadId)}`
            : problem.link
          : null;

        return (
          <div
            key={problem.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${severityColors[problem.severity]}`}
          >
            <span className="text-lg">{problemIcons[problem.type]}</span>
            <span className="flex-1">{problem.message}</span>
            {linkHref && (
              <Link
                href={linkHref}
                className="text-sm underline hover:no-underline opacity-75 hover:opacity-100"
              >
                View Details
              </Link>
            )}
            {onDismiss && (
              <button
                type="button"
                onClick={() => onDismiss(problem.id)}
                className="text-sm opacity-50 hover:opacity-100"
              >
                Dismiss
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Helper to detect problems from trace state
export function detectProblems(state: Record<string, unknown>): Problem[] {
  const problems: Problem[] = [];

  // Hash mismatch
  const reqHash = state.requirements_hash || state.req_hash;
  const evalHash = state.room_eval_hash || state.eval_hash;
  const roomLocked = state.locked_room_id || state.selected_room;
  if (roomLocked && reqHash && evalHash && reqHash !== evalHash) {
    problems.push({
      id: 'hash_mismatch',
      type: 'hash_mismatch',
      message: 'Requirements hash mismatch - room needs re-evaluation',
      severity: 'error',
      link: '/debug/errors',
    });
  }

  // Detour loop detection (would need trace events, simplified here)
  const detourCount = (state.detour_count as number) || 0;
  if (detourCount > 2) {
    problems.push({
      id: 'detour_loop',
      type: 'detour_loop',
      message: `Detour loop detected (${detourCount} detours)`,
      severity: 'warn',
      link: '/debug/errors',
    });
  }

  // Date inconsistency
  const chosenDate = state.chosen_date;
  const displayDate = state.display_date;
  if (chosenDate && displayDate && chosenDate !== displayDate) {
    problems.push({
      id: 'date_inconsistency',
      type: 'date_inconsistency',
      message: `Date mismatch: stored=${chosenDate}, displayed=${displayDate}`,
      severity: 'error',
      link: '/debug/dates',
    });
  }

  return problems;
}

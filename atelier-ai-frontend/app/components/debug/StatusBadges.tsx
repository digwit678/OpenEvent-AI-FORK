'use client';

interface StatusBadge {
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'pending' | 'error' | 'muted';
}

interface StatusBadgesProps {
  badges: StatusBadge[];
  className?: string;
}

export default function StatusBadges({ badges, className = '' }: StatusBadgesProps) {
  const getToneClasses = (tone: StatusBadge['tone']) => {
    switch (tone) {
      case 'ok':
        return 'bg-green-500/10 border-green-500/30 text-green-400';
      case 'warn':
        return 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400';
      case 'error':
        return 'bg-red-500/10 border-red-500/30 text-red-400';
      case 'pending':
        return 'bg-slate-500/10 border-slate-500/30 text-slate-400';
      case 'muted':
      default:
        return 'bg-slate-800/50 border-slate-700 text-slate-500';
    }
  };

  return (
    <div className={`flex flex-wrap gap-3 ${className}`}>
      {badges.map((badge, index) => (
        <div
          key={index}
          className={`px-3 py-2 rounded-lg border ${getToneClasses(badge.tone)}`}
        >
          <div className="text-xs text-slate-500 uppercase tracking-wider">{badge.label}</div>
          <div className="font-medium">{badge.value}</div>
        </div>
      ))}
    </div>
  );
}


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

const TONE_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  ok: { bg: 'rgba(34,197,94,0.1)', border: 'rgba(34,197,94,0.3)', text: '#4ade80' },
  warn: { bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.3)', text: '#fbbf24' },
  error: { bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.3)', text: '#f87171' },
  pending: { bg: 'rgba(100,116,139,0.1)', border: 'rgba(100,116,139,0.3)', text: '#94a3b8' },
  muted: { bg: 'rgba(30,41,59,0.5)', border: '#334155', text: '#64748b' },
};

export default function StatusBadges({ badges, className = '' }: StatusBadgesProps) {
  return (
    <div
      className={`flex flex-wrap gap-4 ${className}`}
      style={{ display: 'flex', flexWrap: 'wrap', gap: '16px' }}
    >
      {badges.map((badge, index) => {
        const styles = TONE_STYLES[badge.tone] || TONE_STYLES.muted;
        return (
          <div
            key={index}
            className="px-4 py-3 rounded-xl border"
            style={{
              padding: '12px 16px',
              borderRadius: '12px',
              backgroundColor: styles.bg,
              border: `1px solid ${styles.border}`,
              minWidth: '110px',
            }}
          >
            <div
              className="text-xs text-slate-500 uppercase tracking-wider"
              style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: '500' }}
            >
              {badge.label}
            </div>
            <div
              className="font-semibold"
              style={{ fontWeight: '600', color: styles.text, fontSize: '15px', marginTop: '4px' }}
            >
              {badge.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}

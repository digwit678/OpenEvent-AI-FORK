'use client';

type TraceBadgeTone = 'ok' | 'pending' | 'warn' | 'info' | 'success' | 'muted';

interface TraceBadgeProps {
  id: string;
  label: string;
  value: string;
  tone: TraceBadgeTone;
  description: string;
}

interface TraceBadgesProps {
  badges: TraceBadgeProps[];
}

export default function TraceBadges({ badges }: TraceBadgesProps) {
  if (!badges.length) {
    return null;
  }
  return (
    <div className="trace-badges">
      {badges.map((badge) => (
        <span key={badge.id} className={`trace-badge trace-badge--${badge.tone}`} title={badge.description}>
          <span className="trace-badge__label">{badge.label}</span>
          <span className="trace-badge__value">{badge.value}</span>
        </span>
      ))}
    </div>
  );
}

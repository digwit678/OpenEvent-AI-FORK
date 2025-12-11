'use client';

import Link from 'next/link';

interface NavCardProps {
  href: string;
  title: string;
  description: string;
  icon: string;
  badge?: { text: string; tone: 'ok' | 'warn' | 'error' | 'info' };
  threadId?: string | null;
}

// Simple inline styles for icons to prevent sizing issues
const iconStyle = { width: '24px', height: '24px', flexShrink: 0 };

export default function NavCard({ href, title, description, icon, badge, threadId }: NavCardProps) {
  const fullHref = threadId ? `${href}?thread=${encodeURIComponent(threadId)}` : href;

  return (
    <Link
      href={fullHref}
      className="group block p-5 bg-slate-800 border border-slate-700 rounded-xl hover:bg-slate-750 hover:border-slate-600 transition-all"
      style={{
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        padding: '20px',
        borderRadius: '12px',
        textDecoration: 'none',
        display: 'block'
      }}
    >
      <div className="flex items-start gap-4" style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
        <span style={{ fontSize: '28px', lineHeight: 1 }}>{icon}</span>
        <div className="flex-1 min-w-0" style={{ flex: 1, minWidth: 0 }}>
          <div className="flex items-center gap-2" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={{ color: '#f1f5f9', fontSize: '18px', fontWeight: '600', margin: 0 }}>
              {title}
            </h3>
            {badge && (
              <span
                style={{
                  fontSize: '11px',
                  padding: '3px 10px',
                  borderRadius: '9999px',
                  backgroundColor: badge.tone === 'error' ? 'rgba(239,68,68,0.2)' : badge.tone === 'warn' ? 'rgba(245,158,11,0.2)' : 'rgba(34,197,94,0.2)',
                  color: badge.tone === 'error' ? '#f87171' : badge.tone === 'warn' ? '#fbbf24' : '#4ade80',
                  fontWeight: '500',
                }}
              >
                {badge.text}
              </span>
            )}
          </div>
          <p style={{ color: '#94a3b8', fontSize: '15px', marginTop: '8px', lineHeight: '1.5', margin: '8px 0 0 0' }}>
            {description}
          </p>
        </div>
        <span style={{ color: '#64748b', fontSize: '18px' }}>&rarr;</span>
      </div>
    </Link>
  );
}

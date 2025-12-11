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

export default function NavCard({ href, title, description, icon, badge, threadId }: NavCardProps) {
  // Append thread param if available
  const fullHref = threadId ? `${href}?thread=${encodeURIComponent(threadId)}` : href;

  return (
    <Link
      href={fullHref}
      className="block p-4 bg-slate-800/50 border border-slate-700 rounded-xl hover:bg-slate-800 hover:border-slate-600 transition-all group"
    >
      <div className="flex items-start gap-3">
        <span className="text-2xl">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-slate-100 group-hover:text-white transition-colors">
              {title}
            </h3>
            {badge && (
              <span
                className={`text-xs px-2 py-0.5 rounded-full ${
                  badge.tone === 'ok'
                    ? 'bg-green-500/20 text-green-400'
                    : badge.tone === 'warn'
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : badge.tone === 'error'
                    ? 'bg-red-500/20 text-red-400'
                    : 'bg-blue-500/20 text-blue-400'
                }`}
              >
                {badge.text}
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">{description}</p>
        </div>
        <span className="text-slate-500 group-hover:text-slate-400 transition-colors">
          &rarr;
        </span>
      </div>
    </Link>
  );
}

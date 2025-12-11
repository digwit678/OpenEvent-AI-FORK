'use client';

import Link from 'next/link';
import { ReactNode } from 'react';
import ThreadSelector, { useThreadId } from './ThreadSelector';

interface DebugHeaderProps {
  title: string;
  icon?: ReactNode;
  children?: ReactNode;
}

// Default bug icon
function BugIcon() {
  return (
    <svg style={{ width: '24px', height: '24px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0112 12.75zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 01-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 002.248-2.354M12 12.75a2.25 2.25 0 01-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 00-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 01.4-2.253M12 8.25a2.25 2.25 0 00-2.248 2.146M12 8.25a2.25 2.25 0 012.248 2.146M8.683 5a6.032 6.032 0 01-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0115.318 5m0 0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 00-.575-1.752M4.921 6a24.048 24.048 0 00-.392 3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 01-5.223 1.082" />
    </svg>
  );
}

function BackArrowIcon() {
  return (
    <svg style={{ width: '18px', height: '18px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

export default function DebugHeader({ title, icon, children }: DebugHeaderProps) {
  const threadId = useThreadId();

  return (
    <header style={{ marginBottom: '28px' }}>
      {/* Top bar with back button and thread selector */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <Link
          href={threadId ? `/debug?thread=${encodeURIComponent(threadId)}` : '/debug'}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '10px',
            fontSize: '15px',
            color: '#94a3b8',
            textDecoration: 'none'
          }}
        >
          <span style={{
            padding: '8px',
            borderRadius: '10px',
            backgroundColor: 'rgba(30,41,59,0.5)',
            border: '1px solid rgba(51,65,85,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <BackArrowIcon />
          </span>
          <span>Back to Dashboard</span>
        </Link>
        <ThreadSelector />
      </div>

      {/* Title section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '52px',
          height: '52px',
          borderRadius: '14px',
          background: 'linear-gradient(to bottom right, rgba(51,65,85,0.5), rgba(30,41,59,0.5))',
          border: '1px solid rgba(51,65,85,0.5)',
          color: '#94a3b8'
        }}>
          {icon || <BugIcon />}
        </div>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: '28px', fontWeight: '700', color: '#f1f5f9', margin: 0, letterSpacing: '-0.025em' }}>{title}</h1>
        </div>
        {children}
      </div>
    </header>
  );
}

// Layout wrapper for debug subpages
interface DebugLayoutProps {
  title: string;
  icon?: ReactNode;
  headerContent?: ReactNode;
  children: ReactNode;
}

export function DebugLayout({ title, icon, headerContent, children }: DebugLayoutProps) {
  return (
    <div
      className="min-h-screen debug-page"
      style={{
        minHeight: '100vh',
        background: 'linear-gradient(to bottom, #0f172a, #0f172a, #020617)',
        color: '#f1f5f9',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
      }}
    >
      <div
        style={{
          position: 'relative',
          maxWidth: '1280px',
          margin: '0 auto',
          padding: '32px 24px'
        }}
      >
        <DebugHeader title={title} icon={icon}>
          {headerContent}
        </DebugHeader>
        <main>{children}</main>
      </div>
    </div>
  );
}

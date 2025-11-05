'use client';

interface ManagerViewProps {
  lines: string[];
  onCopy: (lines: string[]) => void | Promise<void>;
  onDownload: (lines: string[]) => void;
  toast?: { tone: 'ok' | 'error'; message: string } | null;
}

export default function ManagerView({ lines, onCopy, onDownload, toast }: ManagerViewProps) {
  return (
    <aside className="manager-view">
      <header className="manager-view__header">
        <div>
          <h3>Manager View</h3>
          <p>Readable timeline for quick reviews.</p>
        </div>
        <div className="manager-view__actions">
          <button type="button" onClick={() => onCopy(lines)} disabled={lines.length === 0}>
            Copy timeline
          </button>
          <button type="button" onClick={() => onDownload(lines)} disabled={lines.length === 0}>
            Download .txt
          </button>
        </div>
        {toast ? (
          <div className={`manager-view__toast manager-view__toast--${toast.tone}`}>
            {toast.message}
          </div>
        ) : null}
      </header>
      <div className="manager-view__body">
        {lines.length === 0 ? (
          <p className="trace-muted">No timeline entries yet.</p>
        ) : (
          <ul>
            {lines.map((line, index) => (
              <li key={`${index}-${line}`}>{line}</li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

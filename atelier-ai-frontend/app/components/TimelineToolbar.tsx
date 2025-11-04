import React from 'react';

interface TimelineToolbarProps {
  autoScroll: boolean;
  paused: boolean;
  onToggleAutoScroll: () => void;
  onTogglePaused: () => void;
  selectedKinds: string[];
  onKindToggle: (lane: string) => void;
  granularity: 'logic' | 'verbose';
  onGranularityChange: (value: 'logic' | 'verbose') => void;
  onDownloadJson: () => void;
  onDownloadText: () => void;
}

const LANE_LABELS: Record<string, string> = {
  step: 'Step',
  gate: 'Gate',
  db: 'DB',
  entity: 'Entity',
  detour: 'Detour',
  qa: 'Q&A',
  draft: 'Draft',
};

const GRANULARITY_OPTIONS: Array<'logic' | 'verbose'> = ['logic', 'verbose'];

export function TimelineToolbar({
  autoScroll,
  paused,
  onToggleAutoScroll,
  onTogglePaused,
  selectedKinds,
  onKindToggle,
  granularity,
  onGranularityChange,
  onDownloadJson,
  onDownloadText,
}: TimelineToolbarProps) {
  return (
    <div className="trace-toolbar">
      <div className="trace-toolbar__group">
        <button type="button" className={autoScroll ? 'active' : ''} onClick={onToggleAutoScroll}>
          {autoScroll ? 'Auto-scroll On' : 'Auto-scroll Off'}
        </button>
        <button type="button" className={paused ? 'active' : ''} onClick={onTogglePaused}>
          {paused ? 'Resume' : 'Pause'}
        </button>
      </div>

      <div className="trace-toolbar__group">
        <div className="trace-toolbar__chips">
          {GRANULARITY_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={`trace-chip ${granularity === option ? 'trace-chip--active' : ''}`}
              onClick={() => onGranularityChange(option)}
            >
              {option === 'logic' ? 'Logic' : 'Verbose'}
            </button>
          ))}
        </div>
        <div className="trace-toolbar__chips">
          {Object.keys(LANE_LABELS).map((lane) => {
            const active = selectedKinds.includes(lane);
            return (
              <button
                key={lane}
                type="button"
                className={`trace-chip trace-chip--lane lane-chip lane-chip--${lane}${active ? ' trace-chip--active' : ''}`}
                onClick={() => onKindToggle(lane)}
              >
                {LANE_LABELS[lane]}
              </button>
            );
          })}
        </div>
      </div>

      <div className="trace-toolbar__group">
        <button type="button" onClick={onDownloadJson}>
          Download JSONL
        </button>
        <button type="button" onClick={onDownloadText}>
          Download Readable Timeline
        </button>
      </div>
    </div>
  );
}

export default TimelineToolbar;

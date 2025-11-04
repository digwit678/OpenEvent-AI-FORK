import React from 'react';

interface TimelineToolbarProps {
  autoScroll: boolean;
  paused: boolean;
  onToggleAutoScroll: () => void;
  onTogglePaused: () => void;
  laneFilters: Record<string, boolean>;
  onLaneToggle: (lane: string) => void;
  statusFilters: Record<string, boolean>;
  onStatusToggle: (status: string) => void;
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

const STATUS_LABELS: Record<string, string> = {
  captured: 'Captured',
  confirmed: 'Confirmed',
  changed: 'Changed',
  checked: 'Checked',
  pass: 'Pass',
  fail: 'Fail',
};

export function TimelineToolbar({
  autoScroll,
  paused,
  onToggleAutoScroll,
  onTogglePaused,
  laneFilters,
  onLaneToggle,
  statusFilters,
  onStatusToggle,
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
        <div className="trace-toolbar__filters">
          {Object.entries(laneFilters).map(([lane, enabled]) => (
            <label key={lane}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={() => onLaneToggle(lane)}
              />
              {LANE_LABELS[lane] ?? lane}
            </label>
          ))}
        </div>
        <div className="trace-toolbar__filters">
          {Object.entries(statusFilters).map(([status, enabled]) => (
            <label key={status}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={() => onStatusToggle(status)}
              />
              {STATUS_LABELS[status] ?? status}
            </label>
          ))}
        </div>
      </div>

      <div className="trace-toolbar__group">
        <button type="button" onClick={onDownloadJson}>
          Download JSONL
        </button>
        <button type="button" onClick={onDownloadText}>
          Download Arrow Log
        </button>
      </div>
    </div>
  );
}

export default TimelineToolbar;

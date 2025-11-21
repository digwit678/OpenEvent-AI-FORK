'use client';

import { PauseCircle, PlayCircle, Download, LayoutPanelLeft, Copy } from 'lucide-react';
import { SegmentedControl } from './Chips';
import { GranularityLevel } from './utils';

interface ToolbarProps {
  autoScroll: boolean;
  paused: boolean;
  onToggleAutoScroll: () => void;
  onTogglePaused: () => void;
  granularity: GranularityLevel;
  onGranularityChange: (level: GranularityLevel) => void;
  onDownloadJson: () => void;
  onDownloadCsv: () => void;
  onDownloadReadable: () => void;
  onCopyReport: (() => void) | null;
  copyReportDisabled?: boolean;
  copyReportState?: 'idle' | 'copied' | 'error';
  showManagerView: boolean;
  onToggleManagerView: () => void;
}

const GRANULARITY_OPTIONS: Array<{ value: GranularityLevel; label: string }> = [
  { value: 'manager', label: 'Manager' },
  { value: 'logic', label: 'Logic' },
  { value: 'full', label: 'Full' },
];

export default function Toolbar({
  autoScroll,
  paused,
  onToggleAutoScroll,
  onTogglePaused,
  granularity,
  onGranularityChange,
  onDownloadJson,
  onDownloadCsv,
  onDownloadReadable,
  onCopyReport,
  copyReportDisabled = false,
  copyReportState = 'idle',
  showManagerView,
  onToggleManagerView,
}: ToolbarProps) {
  return (
    <div className="trace-toolbar">
      <div className="trace-toolbar__group">
        <button type="button" onClick={onToggleAutoScroll} className={autoScroll ? 'active' : ''}>
          {autoScroll ? 'Auto-scroll On' : 'Auto-scroll Off'}
        </button>
        <button type="button" onClick={onTogglePaused} className={paused ? 'active' : ''}>
          {paused ? (
            <><PlayCircle size={14} /> Resume</>
          ) : (
            <><PauseCircle size={14} /> Pause</>
          )}
        </button>
      </div>

      <div className="trace-toolbar__group">
        <SegmentedControl
          options={GRANULARITY_OPTIONS}
          value={granularity}
          onChange={(value) => onGranularityChange(value as GranularityLevel)}
        />
      </div>

      <div className="trace-toolbar__group">
        <button type="button" onClick={onDownloadJson}>
          <Download size={14} /> JSONL
        </button>
        <button type="button" onClick={onDownloadCsv}>
          <Download size={14} /> CSV
        </button>
        <button type="button" onClick={onDownloadReadable}>
          <Download size={14} /> Timeline
        </button>
        <button
          type="button"
          onClick={onCopyReport ?? undefined}
          disabled={copyReportDisabled || !onCopyReport}
          className={copyReportState === 'error' ? 'error' : copyReportState === 'copied' ? 'active' : ''}
        >
          <Copy size={14} /> {copyReportState === 'copied' ? 'Copied' : copyReportState === 'error' ? 'Copy Failed' : 'Copy Report'}
        </button>
        <button type="button" onClick={onToggleManagerView} className={showManagerView ? 'active' : ''}>
          <LayoutPanelLeft size={14} /> Manager View
        </button>
      </div>
    </div>
  );
}

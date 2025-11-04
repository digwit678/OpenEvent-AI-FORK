import React from 'react';

const LANE_ITEMS = [
  { label: 'Step', className: 'lane-chip lane-chip--step' },
  { label: 'Gate', className: 'lane-chip lane-chip--gate' },
  { label: 'DB', className: 'lane-chip lane-chip--db' },
  { label: 'Entity', className: 'lane-chip lane-chip--entity' },
  { label: 'Detour', className: 'lane-chip lane-chip--detour' },
  { label: 'Q&A', className: 'lane-chip lane-chip--qa' },
  { label: 'Draft', className: 'lane-chip lane-chip--draft' },
];

const STATUS_ITEMS = [
  { label: 'Captured', className: 'status-pill status-pill--captured' },
  { label: 'Confirmed', className: 'status-pill status-pill--confirmed' },
  { label: 'Changed', className: 'status-pill status-pill--changed' },
  { label: 'Checked', className: 'status-pill status-pill--checked' },
  { label: 'Pass', className: 'status-pill status-pill--pass' },
  { label: 'Fail', className: 'status-pill status-pill--fail' },
];

export function TraceLegend() {
  return (
    <div className="trace-legend">
      <span className="font-semibold text-gray-500 uppercase tracking-wide text-[10px]">Lanes</span>
      {LANE_ITEMS.map((item) => (
        <span key={item.label} className="trace-legend__item">
          <span className={item.className}>{item.label}</span>
        </span>
      ))}
      <span className="font-semibold text-gray-500 uppercase tracking-wide text-[10px] ml-2">Status</span>
      {STATUS_ITEMS.map((item) => (
        <span key={item.label} className="trace-legend__item">
          <span className={item.className}>{item.label}</span>
        </span>
      ))}
    </div>
  );
}

export default TraceLegend;

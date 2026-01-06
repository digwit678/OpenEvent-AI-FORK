import React from 'react';
import { SUBLOOP_COLORS, SUBLOOP_LABELS, SubloopKey } from './constants';

const ENTRIES = Object.keys(SUBLOOP_COLORS) as SubloopKey[];

export default function SubloopLegend(): React.ReactElement | null {
  if (!ENTRIES.length) {
    return null;
  }
  return (
    <div className="subloop-legend" aria-label="Subloop legend">
      {ENTRIES.map((key) => (
        <span key={key} className="subloop-legend__item">
          <span
            className="subloop-legend__swatch"
            style={{ backgroundColor: SUBLOOP_COLORS[key] }}
            aria-hidden="true"
            role="presentation"
          />
          <span className="subloop-legend__label">{SUBLOOP_LABELS[key]}</span>
        </span>
      ))}
    </div>
  );
}

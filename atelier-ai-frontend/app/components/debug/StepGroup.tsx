import React from 'react';

import type { GateProgress } from './utils';
import type { TraceSection } from '../trace/TraceTypes';
import type { TraceColumnDef } from '../trace/ColumnDefs';

interface StepGroupProps {
  section: TraceSection & {
    rowElements: React.ReactElement[];
    dimmed?: boolean;
  };
  columns: TraceColumnDef[];
  columnTemplate: string;
  stickyOffsets: number[];
  scrollLeft: number;
}

function renderGateBadge(progress: GateProgress | undefined): React.ReactElement | null {
  if (!progress) {
    return null;
  }
  const ratio = `${progress.completed}/${progress.total}`;
  return (
    <span
      className="trace-progress__badge"
      title={progress.breakdown.map((item) => `${item.met ? '✔' : '○'} ${item.label}`).join('\n')}
    >
      {ratio}
    </span>
  );
}

function renderGateBreakdown(progress: GateProgress | undefined): React.ReactElement | null {
  if (!progress) {
    return null;
  }
  return (
    <div className="trace-progress__chips">
      {progress.breakdown.map((item) => (
        <span key={item.label} className={`trace-chip trace-chip--${item.met ? 'ok' : 'pending'}`} title={item.hint || item.label}>
          {item.label}
        </span>
      ))}
    </div>
  );
}

export default function StepGroup({
  section,
  columns,
  columnTemplate,
  stickyOffsets,
  scrollLeft,
}: StepGroupProps): React.ReactElement {
  const { title, gateProgress, infoChips, rowElements, dimmed, key } = section;
  const sectionClass = dimmed ? 'trace-section trace-section--future' : 'trace-section';
  const headerRowStyle = {
    gridTemplateColumns: columnTemplate,
    transform: `translateX(-${scrollLeft}px)`,
  };

  return (
    <section key={key} className={sectionClass}>
      <header className="trace-section__header">
        <div className="trace-section__title">
          <span>{title}</span>
          {renderGateBadge(gateProgress)}
        </div>
        {renderGateBreakdown(gateProgress)}
        {infoChips?.length ? (
          <div className="trace-section__info">
            {infoChips.map((chip) => (
              <span key={chip} className="trace-chip trace-chip--info">
                {chip}
              </span>
            ))}
          </div>
        ) : null}
      </header>
      <div className="trace-section__grid">
        <div className="trace-table__header-row" style={headerRowStyle}>
          {columns.map((column, index) => {
            const style: React.CSSProperties = {
              width: column.width,
              minWidth: column.width,
              textAlign: column.align || 'left',
              position: column.sticky ? 'sticky' : undefined,
              left: column.sticky ? stickyOffsets[index] : undefined,
              zIndex: column.sticky ? 3 : undefined,
            };
            return (
              <div key={column.id} className={`trace-cell trace-cell__header trace-cell--${column.id}`} style={style}>
                {column.label}
              </div>
            );
          })}
        </div>
        <div className="trace-table__body">
          {rowElements.length === 0 ? (
            <div className="trace-table__empty">No events recorded for this step.</div>
          ) : (
            rowElements
          )}
        </div>
      </div>
    </section>
  );
}

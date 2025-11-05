'use client';

import React from 'react';
import { useDeferredValue, useEffect, useMemo } from 'react';
import type { CSSProperties } from 'react';

import type { GranularityLevel, GateProgress } from '../debug/utils';
import { TRACE_COLUMNS, TraceColumnContext } from './ColumnDefs';
import { TraceRowData, TraceSection } from './TraceTypes';
import { useStickyScroll } from './useStickyScroll';

type RenderedSection = TraceSection & { rowElements: JSX.Element[] };

interface TraceTableProps {
  sections: TraceSection[];
  onInspect: (row: TraceRowData) => void;
  onTimeTravel: (row: TraceRowData) => void;
  hilOpen: boolean;
  granularity: GranularityLevel;
  onRegisterScroller?: (element: HTMLDivElement | null) => void;
  timeTravelStepMajor?: number | null;
  activeTimestamp?: number | null;
}

function renderGateBadge(progress: GateProgress | undefined): JSX.Element | null {
  if (!progress) {
    return null;
  }
  const ratio = `${progress.completed}/${progress.total}`;
  return (
    <span className="trace-progress__badge" title={progress.breakdown.map((item) => `${item.met ? '✔' : '○'} ${item.label}`).join('\n')}>
      {ratio}
    </span>
  );
}

function renderGateBreakdown(progress: GateProgress | undefined): JSX.Element | null {
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

export default function TraceTable({
  sections,
  onInspect,
  onTimeTravel,
  hilOpen,
  granularity,
  onRegisterScroller,
  timeTravelStepMajor,
  activeTimestamp,
}: TraceTableProps) {
  const suspendSticky = Boolean(timeTravelStepMajor !== null || activeTimestamp !== null);
  const { scrollerRef, scrollLeft } = useStickyScroll<HTMLDivElement>({ disabled: suspendSticky });
  const deferredSections = useDeferredValue(sections);

  useEffect(() => {
    if (onRegisterScroller) {
      onRegisterScroller(scrollerRef.current);
      return () => onRegisterScroller(null);
    }
    return undefined;
  }, [onRegisterScroller]);

  const columnTemplate = useMemo(
    () => TRACE_COLUMNS.map((column) => `${column.width}px`).join(' '),
    [],
  );

  const stickyOffsets = useMemo(() => {
    let offset = 0;
    return TRACE_COLUMNS.map((column) => {
      if (column.sticky) {
        const current = offset;
        offset += column.width;
        return current;
      }
      return 0;
    });
  }, []);

  const columnContext: TraceColumnContext = useMemo(
    () => ({ hilOpen, onInspect, onTimeTravel, granularity }),
    [hilOpen, onInspect, onTimeTravel, granularity],
  );

  const renderedSections: RenderedSection[] = useMemo(
    () =>
      deferredSections.map((section) => {
        const isFuture =
          section.dimmed ??
          (typeof timeTravelStepMajor === 'number' &&
            section.stepMajor !== null &&
            section.stepMajor > timeTravelStepMajor);
        const rowElements = section.rows.map((row) => {
          const isActive = activeTimestamp !== null && row.timestamp === activeTimestamp;
          const classes = [
            'trace-table__row',
            isActive ? 'trace-table__row--active' : '',
            row.subloop ? 'trace-table__row--subloop' : '',
          ]
            .filter(Boolean)
            .join(' ');
          const rowStyle: CSSProperties = {
            gridTemplateColumns: columnTemplate,
          };
          if (row.subloopColor) {
            rowStyle.borderLeft = `4px solid ${row.subloopColor}`;
          }
          const cells = TRACE_COLUMNS.map((column, index) => {
            const style: CSSProperties = {
              width: column.width,
              minWidth: column.width,
              textAlign: column.align || 'left',
            };
            if (column.sticky) {
              style.position = 'sticky';
              style.left = stickyOffsets[index];
              style.zIndex = 2;
            }
            return (
              <div key={column.id} className={`trace-cell trace-cell--${column.id}`} style={style}>
                {column.render(row, columnContext)}
              </div>
            );
          });
          return (
            <div key={row.id} className={classes} style={rowStyle}>
              {cells}
            </div>
          );
        });
        return {
          ...section,
          dimmed: isFuture,
          rowElements,
        };
      }),
    [deferredSections, columnTemplate, stickyOffsets, columnContext, timeTravelStepMajor, activeTimestamp],
  );

  return (
    <div className="trace-table__container">
      <div className="trace-table__scroller" ref={scrollerRef}>
        {renderedSections.map((section) => {
          const future = section.dimmed;
          const sectionClass = future ? 'trace-section trace-section--future' : 'trace-section';
          return (
            <section key={section.key} className={sectionClass}>
              <header className="trace-section__header">
                <div className="trace-section__title">
                  <span>{section.title}</span>
                  {renderGateBadge(section.gateProgress)}
                </div>
                {renderGateBreakdown(section.gateProgress)}
                {section.infoChips?.length ? (
                  <div className="trace-section__info">
                    {section.infoChips.map((chip) => (
                      <span key={chip} className="trace-chip trace-chip--info">{chip}</span>
                    ))}
                  </div>
                ) : null}
              </header>
              <div className="trace-section__grid">
                <div
                  className="trace-table__header-row"
                  style={{ gridTemplateColumns: columnTemplate, transform: `translateX(-${scrollLeft}px)` }}
                >
                  {TRACE_COLUMNS.map((column, index) => {
                    const style: CSSProperties = {
                      width: column.width,
                      minWidth: column.width,
                    };
                    if (column.sticky) {
                      style.position = 'sticky';
                      style.left = stickyOffsets[index];
                      style.zIndex = 3;
                    }
                    return (
                      <div key={column.id} className={`trace-cell trace-cell__header trace-cell--${column.id}`} style={style}>
                        {column.label}
                      </div>
                    );
                  })}
                </div>
                <div className="trace-table__body">
                  {section.rowElements.length === 0 ? (
                    <div className="trace-table__empty">No events recorded for this step.</div>
                  ) : (
                    section.rowElements
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

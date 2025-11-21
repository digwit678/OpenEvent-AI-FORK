'use client';

import React from 'react';
import { useDeferredValue, useEffect, useMemo } from 'react';
import type { CSSProperties } from 'react';

import type { GranularityLevel } from '../debug/utils';
import { TRACE_COLUMNS, TraceColumnContext } from './ColumnDefs';
import { TraceRowData, TraceSection } from './TraceTypes';
import { useStickyScroll } from './useStickyScroll';
import StepGroup from '../debug/StepGroup';

type RenderedSection = TraceSection & { rowElements: JSX.Element[]; dimmed?: boolean };

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
        {renderedSections.map((section) => (
          <StepGroup
            key={section.key}
            section={section}
            columns={TRACE_COLUMNS}
            columnTemplate={columnTemplate}
            stickyOffsets={stickyOffsets}
            scrollLeft={scrollLeft}
          />
        ))}
      </div>
    </div>
  );
}

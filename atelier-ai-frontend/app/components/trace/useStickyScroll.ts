'use client';

import { MutableRefObject, useEffect, useRef, useState } from 'react';

export interface StickyScrollHandle<T extends HTMLElement> {
  scrollerRef: MutableRefObject<T | null>;
  scrollLeft: number;
}

interface StickyScrollOptions {
  disabled?: boolean;
}

export function useStickyScroll<T extends HTMLElement>(options?: StickyScrollOptions): StickyScrollHandle<T> {
  const disabled = options?.disabled ?? false;
  const scrollerRef = useRef<T | null>(null);
  const [scrollLeft, setScrollLeft] = useState(0);
  const lastScrollLeft = useRef(0);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || disabled) {
      return () => {};
    }
    let ticking = false;
    const handleScroll = () => {
      if (ticking) {
        return;
      }
      ticking = true;
      window.requestAnimationFrame(() => {
        const next = scroller.scrollLeft;
        lastScrollLeft.current = next;
        setScrollLeft(next);
        ticking = false;
      });
    };
    scroller.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      scroller.removeEventListener('scroll', handleScroll);
    };
  }, [disabled]);

  useEffect(() => {
    if (disabled) {
      setScrollLeft(lastScrollLeft.current);
    }
  }, [disabled]);

  return { scrollerRef, scrollLeft };
}

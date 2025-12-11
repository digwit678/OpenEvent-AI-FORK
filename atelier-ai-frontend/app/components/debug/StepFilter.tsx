'use client';

import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { useCallback, useEffect } from 'react';

const STEPS = [1, 2, 3, 4, 5, 6, 7];
const STEP_NAMES: Record<number, string> = {
  1: 'Intake',
  2: 'Date',
  3: 'Room',
  4: 'Offer',
  5: 'Negotiation',
  6: 'Transition',
  7: 'Confirmation',
};

interface StepFilterProps {
  currentStep?: number | null;
  onStepChange?: (step: number | null) => void;
  availableSteps?: number[];
}

export function useStepFilter() {
  const searchParams = useSearchParams();
  const stepParam = searchParams.get('step');
  const selectedStep = stepParam ? parseInt(stepParam, 10) : null;
  return { selectedStep: Number.isNaN(selectedStep) ? null : selectedStep };
}

export default function StepFilter({ currentStep, onStepChange, availableSteps }: StepFilterProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const stepParam = searchParams.get('step');
  const selectedStep = stepParam ? parseInt(stepParam, 10) : null;
  const effectiveStep = Number.isNaN(selectedStep) ? null : selectedStep;

  const handleStepClick = useCallback(
    (step: number | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (step === null) {
        params.delete('step');
      } else {
        params.set('step', String(step));
      }
      const queryString = params.toString();
      const newUrl = queryString ? `${pathname}?${queryString}` : pathname;
      router.push(newUrl, { scroll: false });

      if (onStepChange) {
        onStepChange(step);
      }

      // Scroll to step anchor if selecting a step
      if (step !== null) {
        setTimeout(() => {
          const anchor = document.getElementById(`step-${step}`);
          if (anchor) {
            anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }, 100);
      }
    },
    [searchParams, router, pathname, onStepChange]
  );

  // On mount, scroll to step if in URL
  useEffect(() => {
    if (effectiveStep !== null) {
      const anchor = document.getElementById(`step-${effectiveStep}`);
      if (anchor) {
        anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }, []);

  return (
    <div style={{
      backgroundColor: 'rgba(30,41,59,0.5)',
      border: '1px solid #334155',
      borderRadius: '12px',
      padding: '14px 18px'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '14px', color: '#94a3b8', fontWeight: '500' }}>Filter by Step:</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          <button
            type="button"
            onClick={() => handleStepClick(null)}
            style={{
              padding: '8px 14px',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              border: 'none',
              cursor: 'pointer',
              backgroundColor: effectiveStep === null ? '#475569' : '#1e293b',
              color: effectiveStep === null ? '#ffffff' : '#94a3b8',
              transition: 'all 0.2s'
            }}
          >
            All
          </button>
          {STEPS.map((step) => {
            const isAvailable = !availableSteps || availableSteps.includes(step);
            const isSelected = effectiveStep === step;
            const isCurrent = currentStep === step;

            return (
              <button
                key={step}
                type="button"
                onClick={() => handleStepClick(step)}
                disabled={!isAvailable}
                title={`${STEP_NAMES[step]}${isCurrent ? ' (current)' : ''}${!isAvailable ? ' (no events)' : ''}`}
                style={{
                  padding: '8px 14px',
                  borderRadius: '8px',
                  fontSize: '14px',
                  fontWeight: '500',
                  border: isCurrent && !isSelected ? '2px solid rgba(59,130,246,0.5)' : 'none',
                  cursor: isAvailable ? 'pointer' : 'not-allowed',
                  backgroundColor: isSelected ? '#3b82f6' : isCurrent ? '#334155' : isAvailable ? '#1e293b' : '#0f172a',
                  color: isSelected ? '#ffffff' : isCurrent ? '#60a5fa' : isAvailable ? '#94a3b8' : '#475569',
                  position: 'relative',
                  transition: 'all 0.2s'
                }}
              >
                {step}
                {isCurrent && !isSelected && (
                  <span style={{
                    position: 'absolute',
                    top: '-4px',
                    right: '-4px',
                    width: '8px',
                    height: '8px',
                    backgroundColor: '#3b82f6',
                    borderRadius: '50%'
                  }} />
                )}
              </button>
            );
          })}
        </div>
        {effectiveStep !== null && (
          <span style={{ fontSize: '13px', color: '#64748b', marginLeft: '8px' }}>
            Step {effectiveStep}: {STEP_NAMES[effectiveStep]}
          </span>
        )}
      </div>
    </div>
  );
}

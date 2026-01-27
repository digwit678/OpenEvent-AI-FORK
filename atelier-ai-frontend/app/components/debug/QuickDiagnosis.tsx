'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

interface DiagnosisOption {
  id: string;
  label: string;
  description: string;
  panel: string;
  defaultStep?: number;
  icon: React.ReactNode;
}

// Icon components - all with inline style fallbacks to prevent CSS sizing issues
function SearchIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  );
}

function LoopIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  );
}

function RoomIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
    </svg>
  );
}

function BotIcon() {
  return (
    <svg style={{ width: '20px', height: '20px' }} className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
    <svg style={{ width: '16px', height: '16px' }} className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
    </svg>
  );
}

const DIAGNOSIS_OPTIONS: DiagnosisOption[] = [
  {
    id: 'classification',
    label: 'Wrong response/classification',
    description: 'AI misunderstood intent or gave wrong type of response',
    panel: 'detection',
    defaultStep: 1,
    icon: <SearchIcon />,
  },
  {
    id: 'date',
    label: 'Date shown incorrectly',
    description: 'Date parsed wrong, displayed wrong, or mismatched',
    panel: 'dates',
    defaultStep: 2,
    icon: <CalendarIcon />,
  },
  {
    id: 'loop',
    label: 'Stuck in a loop (detours)',
    description: 'Workflow keeps going back and forth between steps',
    panel: 'errors',
    defaultStep: 3,
    icon: <LoopIcon />,
  },
  {
    id: 'room',
    label: 'Room/offer issue',
    description: 'Room availability, selection, or offer problems',
    panel: 'timeline',
    defaultStep: 3,
    icon: <RoomIcon />,
  },
  {
    id: 'hil',
    label: 'HIL task problem',
    description: 'Approval task missing, wrong step, or stuck',
    panel: 'hil',
    icon: <UserIcon />,
  },
  {
    id: 'llm',
    label: 'LLM said something weird',
    description: 'Check the actual prompts and responses',
    panel: 'agents',
    icon: <BotIcon />,
  },
];

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

interface QuickDiagnosisProps {
  threadId: string | null;
  currentStep?: number | null;
  routingHints?: Record<string, { reason: string; step?: number }>;
}

export default function QuickDiagnosis({ threadId, currentStep, routingHints }: QuickDiagnosisProps) {
  const router = useRouter();
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);

  const handleOptionSelect = (optionId: string) => {
    setSelectedOption(optionId);
    const option = DIAGNOSIS_OPTIONS.find((o) => o.id === optionId);
    if (option?.defaultStep && !selectedStep) {
      setSelectedStep(option.defaultStep);
    }
  };

  const handleGo = () => {
    if (!selectedOption) return;
    const option = DIAGNOSIS_OPTIONS.find((o) => o.id === selectedOption);
    if (!option) return;

    const step = selectedStep || option.defaultStep;
    let url = `/debug/${option.panel}`;
    const params = new URLSearchParams();
    if (threadId) params.set('thread', threadId);
    if (step) params.set('step', String(step));

    const queryString = params.toString();
    if (queryString) url += `?${queryString}`;
    if (step) url += `#step-${step}`;

    router.push(url);
  };

  // Check if we have routing hints from backend
  const suggestedPanel = routingHints ? Object.keys(routingHints)[0] : null;
  const suggestedHint = suggestedPanel ? routingHints?.[suggestedPanel] : null;

  return (
    <div
      className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 border border-slate-700/50 rounded-2xl p-7"
      style={{
        background: 'linear-gradient(to bottom right, rgba(30,41,59,0.5), rgba(15,23,42,0.5))',
        border: '1px solid rgba(51,65,85,0.5)',
        borderRadius: '16px',
        padding: '28px'
      }}
    >
      <h3
        className="text-xl font-semibold text-slate-200 mb-6 flex items-center gap-3"
        style={{ fontSize: '20px', fontWeight: '600', color: '#e2e8f0', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}
      >
        <div style={{ padding: '10px', borderRadius: '10px', backgroundColor: 'rgba(139,92,246,0.1)', color: '#a78bfa' }}>
          <SearchIcon />
        </div>
        Quick Diagnosis
      </h3>

      {suggestedHint && (
        <div className="mb-5 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl">
          <p className="text-sm text-amber-400">
            <strong>Suggested:</strong> {suggestedHint.reason}
            {suggestedHint.step && ` (Step ${suggestedHint.step})`}
          </p>
          <button
            type="button"
            onClick={() => {
              setSelectedOption(
                DIAGNOSIS_OPTIONS.find((o) => o.panel === suggestedPanel)?.id || null
              );
              if (suggestedHint.step) setSelectedStep(suggestedHint.step);
            }}
            className="mt-2 text-xs text-amber-400 underline hover:text-amber-300 transition-colors"
          >
            Use suggestion
          </button>
        </div>
      )}

      <div className="mb-6" style={{ marginBottom: '24px' }}>
        <label style={{ fontSize: '15px', color: '#94a3b8', marginBottom: '14px', display: 'block', fontWeight: '500' }}>What happened?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '12px' }}>
          {DIAGNOSIS_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => handleOptionSelect(option.id)}
              style={{
                textAlign: 'left',
                padding: '16px',
                borderRadius: '12px',
                border: selectedOption === option.id ? '1px solid rgba(139,92,246,0.5)' : '1px solid rgba(51,65,85,0.5)',
                backgroundColor: selectedOption === option.id ? 'rgba(139,92,246,0.15)' : 'rgba(30,41,59,0.3)',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
                <div style={{
                  padding: '10px',
                  borderRadius: '10px',
                  backgroundColor: selectedOption === option.id ? 'rgba(139,92,246,0.2)' : 'rgba(51,65,85,0.5)',
                  color: selectedOption === option.id ? '#a78bfa' : '#64748b'
                }}>
                  {option.icon}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: '500', fontSize: '15px', color: selectedOption === option.id ? '#c4b5fd' : '#cbd5e1' }}>
                    {option.label}
                  </div>
                  <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>{option.description}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="mb-6" style={{ marginBottom: '24px' }}>
        <label style={{ fontSize: '15px', color: '#94a3b8', marginBottom: '14px', display: 'block', fontWeight: '500' }}>At which step? (optional)</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
          <button
            type="button"
            onClick={() => setSelectedStep(null)}
            style={{
              padding: '10px 18px',
              borderRadius: '10px',
              fontSize: '14px',
              fontWeight: '500',
              border: selectedStep === null ? 'none' : '1px solid rgba(51,65,85,0.5)',
              backgroundColor: selectedStep === null ? '#475569' : 'rgba(30,41,59,0.5)',
              color: selectedStep === null ? '#ffffff' : '#94a3b8',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            Any
          </button>
          {STEPS.map((step) => (
            <button
              key={step}
              type="button"
              onClick={() => setSelectedStep(step)}
              style={{
                padding: '10px 18px',
                borderRadius: '10px',
                fontSize: '14px',
                fontWeight: '500',
                border: selectedStep === step ? 'none' : currentStep === step ? '2px solid rgba(139,92,246,0.5)' : '1px solid rgba(51,65,85,0.5)',
                backgroundColor: selectedStep === step ? '#8b5cf6' : currentStep === step ? 'rgba(51,65,85,0.5)' : 'rgba(30,41,59,0.5)',
                color: selectedStep === step ? '#ffffff' : currentStep === step ? '#e2e8f0' : '#94a3b8',
                cursor: 'pointer',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
              title={STEP_NAMES[step]}
            >
              {step}
              {currentStep === step && (
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#a78bfa', display: 'inline-block' }} />
              )}
            </button>
          ))}
        </div>
        {selectedStep && (
          <p style={{ fontSize: '13px', color: '#64748b', marginTop: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#a78bfa' }} />
            Step {selectedStep}: {STEP_NAMES[selectedStep]}
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={handleGo}
        disabled={!selectedOption}
        style={{
          width: '100%',
          padding: '14px',
          borderRadius: '12px',
          fontWeight: '600',
          fontSize: '15px',
          border: 'none',
          cursor: selectedOption ? 'pointer' : 'not-allowed',
          background: selectedOption ? 'linear-gradient(to right, #8b5cf6, #7c3aed)' : 'rgba(51,65,85,0.5)',
          color: selectedOption ? '#ffffff' : '#64748b',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          transition: 'all 0.2s',
        }}
      >
        Go to Panel
        <ArrowRightIcon />
      </button>
    </div>
  );
}

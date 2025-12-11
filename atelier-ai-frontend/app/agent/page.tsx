'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Script from 'next/script';
import { useChatKit, ChatKit } from '@openai/chatkit-react';

const BACKEND_BASE = (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const CHATKIT_DOMAIN_KEY = process.env.NEXT_PUBLIC_CHATKIT_DOMAIN_KEY || 'local-development';
const VERBALIZER_TONE = (process.env.NEXT_PUBLIC_VERBALIZER_TONE || 'empathetic').toLowerCase();

type ClientToolId = 'confirm_offer' | 'change_offer' | 'discard_offer' | 'see_catering' | 'see_products';

const CLIENT_TOOL_BUTTONS: Array<{ id: ClientToolId; label: string }> = [
  { id: 'confirm_offer', label: 'Confirm Offer' },
  { id: 'change_offer', label: 'Change Offer' },
  { id: 'discard_offer', label: 'Discard Offer' },
  { id: 'see_catering', label: 'See Catering' },
  { id: 'see_products', label: 'See Products' },
];

const TOOL_PRESETS: Array<{ id: string; label: string; text: string }> = [
  { id: 'see_catering', label: 'Show Catering', text: 'What catering options are available?' },
  { id: 'see_products', label: 'Show Products', text: 'Which products or equipment can be added?' },
];

function QuickActionBar({ visible, onAction }: { visible: boolean; onAction: (toolId: ClientToolId) => void }) {
  const handleClick = (toolId: ClientToolId) => {
    onAction(toolId);
  };

  if (!visible) {
    return null;
  }

  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {CLIENT_TOOL_BUTTONS.map((action) => (
        <button
          key={action.id}
          type="button"
          onClick={() => handleClick(action.id)}
          className="rounded-full bg-slate-900 text-white px-4 py-2 text-sm font-medium shadow-sm transition hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-500"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}

export default function AgentChatPage() {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [showActions, setShowActions] = useState(false);
  const [resumePrompt, setResumePrompt] = useState<string | null>(null);

  const fillComposerAndSend = useCallback((text: string) => {
    const root = shellRef.current;
    if (!root) {
      return;
    }

    const composer = root.querySelector<HTMLTextAreaElement>('textarea');
    if (!composer) {
      return;
    }

    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(composer, text);
    composer.dispatchEvent(new Event('input', { bubbles: true }));

    const submitButton =
      root.querySelector<HTMLButtonElement>('button[type="submit"]') ??
      root.querySelector<HTMLButtonElement>('button[data-testid="chatkit-send-button"]');
    submitButton?.click();
  }, []);

  const triggerClientTool = useCallback(
    (toolId: ClientToolId) => {
      const payload: { client_tool: ClientToolId; args: Record<string, unknown> } = {
        client_tool: toolId,
        args: {},
      };
      if (toolId === 'change_offer') {
        const note = window.prompt('What would you like to change about the offer?');
        if (!note) {
          return;
        }
        payload.args.note = note;
      } else if (toolId === 'see_catering' || toolId === 'see_products') {
        const roomId = window.prompt('Which room should I reference?');
        if (!roomId) {
          return;
        }
        payload.args.room_id = roomId.trim();
      }
      fillComposerAndSend(JSON.stringify(payload));
    },
    [fillComposerAndSend],
  );

  useEffect(() => {
    const node = shellRef.current;
    if (!node) {
      return;
    }

    const checkForOfferActions = () => {
      const candidates = node.querySelectorAll<HTMLElement>(
        '[data-role="assistant-message"], [data-participant-role="assistant"], [data-testid="assistant-message"]',
      );
      let lastText = '';
      candidates.forEach((item) => {
        const text = item.textContent?.trim();
        if (text) {
          lastText = text;
        }
      });
      if (!candidates.length) {
        const allParagraphs = node.querySelectorAll<HTMLElement>('p');
        allParagraphs.forEach((item) => {
          const text = item.textContent?.trim();
          if (text) {
            lastText = text;
          }
        });
      }
      setShowActions(Boolean(lastText && lastText.includes('Confirm Offer | Change Offer | Discard Offer')));
      const resumeMatch = lastText.match(/(?:Proceed|Continue) with ([^?]+)\?/i);
      setResumePrompt(resumeMatch ? resumeMatch[1].trim() : null);
    };

    checkForOfferActions();
    const observer = new MutationObserver(() => checkForOfferActions());
    observer.observe(node, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  const chatKitOptions = useMemo(
    () => ({
      backend: {
        type: 'custom' as const,
        url: `${BACKEND_BASE}/api/chatkit/respond`,
        uploadStrategy: {
          type: 'direct' as const,
          url: `${BACKEND_BASE}/api/chatkit/upload`,
        },
      },
      domainKey: CHATKIT_DOMAIN_KEY,
      api: {
        async getClientSecret(existing?: string) {
          if (existing) {
            return existing;
          }
          try {
            const response = await fetch(`${BACKEND_BASE}/api/chatkit/session`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
            });
            if (!response.ok) {
              throw new Error(`ChatKit session failed (${response.status})`);
            }
            const payload = await response.json();
            return payload.client_secret;
          } catch (error) {
            console.warn('ChatKit session token failed; using fallback secret.', error);
            return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
          }
        },
      },
      composer: {
        placeholder: 'Type your message...',
        tools: TOOL_PRESETS.map((tool) => ({
          id: tool.id,
          label: tool.label,
          type: 'quick_reply',
          payload: { text: tool.text },
        })) as any,
      },
    }),
    [],
  );

  const { control } = useChatKit(chatKitOptions as any);

  return (
    <>
      <Script src="https://cdn.platform.openai.com/deployments/chatkit/chatkit.js" async />
      <main className="min-h-screen bg-gradient-to-br from-slate-100 to-slate-200 flex items-center justify-center p-4">
        <div className="w-full max-w-4xl bg-white shadow-xl rounded-3xl overflow-hidden border border-slate-200">
          <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-semibold text-slate-800">OpenEvent Agent Chat</h1>
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-slate-200 text-slate-700">
                Tone: {VERBALIZER_TONE === 'plain' ? 'Plain' : 'Empathetic'}
              </span>
            </div>
            <p className="text-sm text-slate-500 mt-1">
              Talk directly to the workflow-backed assistant. Messages route through our FastAPI backend and reuse Workflow v3 logic.
            </p>
          </div>
          <div className="h-[640px] flex flex-col">
            <div ref={shellRef} className="flex-1 overflow-hidden">
              <ChatKit control={control} />
            </div>
            <div className="px-6 py-4 border-t border-slate-200 bg-white">
              <QuickActionBar
                visible={showActions}
                onAction={(toolId) => {
                  triggerClientTool(toolId);
                }}
              />
              {resumePrompt && (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() => fillComposerAndSend('yes')}
                    className="rounded-full border border-slate-400 text-slate-700 px-4 py-2 text-sm font-medium shadow-sm transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-500"
                  >
                    Proceed with {resumePrompt}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

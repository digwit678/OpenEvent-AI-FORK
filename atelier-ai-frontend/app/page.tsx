'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Send, CheckCircle, XCircle, Loader2 } from 'lucide-react';

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

interface MessageMeta {
  confirmDate?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  meta?: MessageMeta;
  streaming?: boolean;
}

interface EventInfo {
  [key: string]: string;
}

interface PendingTaskPayload {
  snippet?: string | null;
  suggested_dates?: string[] | null;
}

interface PendingTask {
  task_id: string;
  type: string;
  client_id?: string | null;
  event_id?: string | null;
  created_at?: string | null;
  notes?: string | null;
  payload?: PendingTaskPayload | null;
}

interface PendingActions {
  type?: string;
  date?: string;
}

interface WorkflowReply {
  session_id?: string | null;
  workflow_type?: string | null;
  response: string;
  is_complete: boolean;
  event_info?: EventInfo | null;
  pending_actions?: PendingActions | null;
}

function debounce<T extends (...args: any[]) => void>(fn: T, delay: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Parameters<T>) => {
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function requestJSON<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  if (response.status === 204) {
    return {} as T;
  }
  return (await response.json()) as T;
}

async function fetchWorkflowReply(url: string, payload: unknown): Promise<WorkflowReply> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const decoder = new TextDecoder();
  let buffer = '';
  if (response.body) {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
    }
    buffer += decoder.decode();
  } else {
    buffer = await response.text();
  }

  if (!response.ok) {
    throw new Error(buffer || `Request failed with status ${response.status}`);
  }
  if (!buffer.trim()) {
    return { response: '', is_complete: false };
  }
  try {
    return JSON.parse(buffer) as WorkflowReply;
  } catch (err) {
    console.error('Unable to parse workflow reply', err);
    throw err;
  }
}

function extractEmail(text: string): string {
  const emailRegex = /[\w.-]+@[\w.-]+\.[A-Za-z]{2,}/;
  const match = text.match(emailRegex);
  return match ? match[0] : 'unknown@example.com';
}

function buildMeta(pending: PendingActions | null | undefined): MessageMeta | undefined {
  if (pending?.type === 'confirm_date' && typeof pending.date === 'string') {
    return { confirmDate: pending.date };
  }
  return undefined;
}

function shouldDisplayEventField(key: string, value: string): boolean {
  if (value === 'Not specified' || value === 'none') {
    return false;
  }
  const lowerKey = key.toLowerCase();
  if (lowerKey.includes('room_') && lowerKey.endsWith('_status')) {
    return false;
  }
  return true;
}

export default function EmailThreadUI() {
  const isMountedRef = useRef(true);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workflowType, setWorkflowType] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draftInput, setDraftInput] = useState('');
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [eventInfo, setEventInfo] = useState<EventInfo | null>(null);
  const [tasks, setTasks] = useState<PendingTask[]>([]);
  const [taskActionId, setTaskActionId] = useState<string | null>(null);
  const [taskNotes, setTaskNotes] = useState<Record<string, string>>({});
  const [hasStarted, setHasStarted] = useState(false);
  const [isUserNearBottom, setIsUserNearBottom] = useState(true);
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);

  const inputDebounce = useMemo(() => debounce((value: string) => setInputText(value), 80), []);

  const appendMessage = useCallback((message: Omit<Message, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setMessages((prev) => [...prev, { ...message, id }]);
    return id;
  }, []);

  const updateMessageAt = useCallback((messageId: string, updater: (msg: Message) => Message) => {
    setMessages((prev) => {
      const index = prev.findIndex((msg) => msg.id === messageId);
      if (index === -1) {
        return prev;
      }
      const updated = updater(prev[index]);
      if (updated === prev[index]) {
        return prev;
      }
      const next = [...prev];
      next[index] = updated;
      return next;
    });
  }, []);

  const stopStreaming = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const streamMessageContent = useCallback(
    (messageId: string, fullText: string) =>
      new Promise<void>((resolve) => {
        stopStreaming();
        if (!fullText) {
          updateMessageAt(messageId, (msg) => ({ ...msg, content: '', streaming: false }));
          resolve();
          return;
        }
        const chunkSize = Math.max(2, Math.ceil(fullText.length / 40));
        let cursor = 0;
        const step = () => {
          cursor = Math.min(fullText.length, cursor + chunkSize);
          const nextSlice = fullText.slice(0, cursor);
          updateMessageAt(messageId, (msg) => ({ ...msg, content: nextSlice, streaming: cursor < fullText.length }));
          if (cursor < fullText.length) {
            rafRef.current = requestAnimationFrame(step);
          } else {
            rafRef.current = null;
            resolve();
          }
        };
        rafRef.current = requestAnimationFrame(step);
      }),
    [stopStreaming, updateMessageAt]
  );

  const handleAssistantReply = useCallback(
    async (messageId: string, reply: WorkflowReply) => {
      await streamMessageContent(messageId, reply.response || '');
      updateMessageAt(messageId, (msg) => ({
        ...msg,
        streaming: false,
        timestamp: new Date(),
        meta: buildMeta(reply.pending_actions) ?? msg.meta,
      }));

      if (reply.workflow_type) {
        setWorkflowType(reply.workflow_type);
      }
      if (reply.session_id !== undefined) {
        setSessionId(reply.session_id ?? null);
      }
      if (reply.event_info !== undefined) {
        setEventInfo(reply.event_info ?? null);
      }
      setIsComplete(reply.is_complete);
    },
    [streamMessageContent, updateMessageAt]
  );

  const refreshTasks = useCallback(async () => {
    try {
      const data = await requestJSON<{ tasks: PendingTask[] }>(`${API_BASE}/tasks/pending`);
      if (!isMountedRef.current) {
        return;
      }
      setTasks(Array.isArray(data.tasks) ? data.tasks : []);
    } catch (error) {
      if (isMountedRef.current) {
        // Downgrade to warn to avoid dev overlay while backend is offline
        console.warn('Tasks polling failed (backend offline?):', error);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    // Ping backend health and start polling only when reachable
    let cancelled = false;
    const checkHealth = async () => {
      try {
        await requestJSON(`${API_BASE}/workflow/health`);
        if (!cancelled) {
          setBackendHealthy(true);
          setBackendError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setBackendHealthy(false);
          setBackendError(`Cannot reach backend at ${API_BASE}`);
        }
      }
    };
    checkHealth().then(() => {
      if (backendHealthy !== false) {
        refreshTasks().catch(() => undefined);
      }
    });
    const healthInterval = window.setInterval(() => {
      checkHealth().catch(() => undefined);
    }, 15000);
    const tasksInterval = window.setInterval(() => {
      if (backendHealthy) {
        refreshTasks().catch(() => undefined);
      }
    }, 5000);
    return () => {
      isMountedRef.current = false;
      stopStreaming();
      cancelled = true;
      window.clearInterval(healthInterval);
      window.clearInterval(tasksInterval);
    };
  }, [refreshTasks, stopStreaming, backendHealthy]);

  useEffect(() => {
    if (!isUserNearBottom) {
      return;
    }
    const container = threadRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, isUserNearBottom]);

  const handleInputChange = useCallback(
    (value: string) => {
      setDraftInput(value);
      inputDebounce(value);
    },
    [inputDebounce]
  );

  const handleThreadScroll = useMemo(
    () =>
      debounce((element: HTMLDivElement) => {
        const { scrollTop, scrollHeight, clientHeight } = element;
        const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
        setIsUserNearBottom(distanceFromBottom < 32);
      }, 120),
    []
  );

  const startConversation = useCallback(async () => {
    const trimmed = draftInput.trim();
    if (!trimmed) {
      return;
    }
    setIsLoading(true);
    const email = extractEmail(trimmed);
    setMessages(() => []);
    appendMessage({
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
    });
    setHasStarted(true);
    setIsComplete(false);
    setEventInfo(null);

    const assistantId = appendMessage({
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      streaming: true,
    });

    try {
      const reply = await fetchWorkflowReply(`${API_BASE}/start-conversation`, {
        email_body: trimmed,
        client_email: email,
      });
      await handleAssistantReply(assistantId, reply);
      if (reply.session_id) {
        setSessionId(reply.session_id);
      }
      refreshTasks().catch(() => undefined);
    } catch (error) {
      console.error('Error starting conversation:', error);
      updateMessageAt(assistantId, (msg) => ({
        ...msg,
        streaming: false,
        content: 'Error connecting to server. Make sure backend is running on port 8000.',
      }));
    } finally {
      setDraftInput('');
      setInputText('');
      setIsLoading(false);
    }
  }, [appendMessage, draftInput, handleAssistantReply, refreshTasks, updateMessageAt]);

  const sendMessage = useCallback(async () => {
    const trimmed = draftInput.trim();
    if (!trimmed || !sessionId) {
      return;
    }
    setIsLoading(true);
    const userMessage: Omit<Message, 'id'> = {
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
    };
    appendMessage(userMessage);

    const assistantId = appendMessage({
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      streaming: true,
    });

    setDraftInput('');
    setInputText('');

    try {
      const reply = await fetchWorkflowReply(`${API_BASE}/send-message`, {
        session_id: sessionId,
        message: trimmed,
      });
      await handleAssistantReply(assistantId, reply);
      refreshTasks().catch(() => undefined);
    } catch (error) {
      console.error('Error sending message:', error);
      updateMessageAt(assistantId, (msg) => ({
        ...msg,
        streaming: false,
        content: 'Error sending message. Please try again.',
      }));
    } finally {
      setIsLoading(false);
    }
  }, [appendMessage, draftInput, handleAssistantReply, refreshTasks, sessionId, updateMessageAt]);

  const handleTaskAction = useCallback(
    async (task: PendingTask, decision: 'approve' | 'reject') => {
      if (!task.task_id) {
        return;
      }
      setTaskActionId(task.task_id);
      try {
        const notes = taskNotes[task.task_id] || undefined;
        await requestJSON(`${API_BASE}/tasks/${task.task_id}/${decision}`, {
          method: 'POST',
          body: JSON.stringify({ notes }),
        });
        if (sessionId) {
          const note = (taskNotes[task.task_id] || '').trim();
          let content = '';
          if (task.type === 'ask_for_date') {
            content =
              decision === 'approve'
                ? "I've proposed these dates to the client. Please pick one."
                : "I won't send the date suggestion yet.";
          } else if (task.type === 'manual_review') {
            content =
              decision === 'approve'
                ? `Manual review approved.${note ? ' ' + note : ''}`
                : `Manual review rejected.${note ? ' ' + note : ''}`;
          }
          if (content) {
            appendMessage({ role: 'assistant', content, timestamp: new Date() });
          }
        }
        refreshTasks().catch(() => undefined);
      } catch (error) {
        console.error(`Error updating task (${decision}):`, error);
        alert('Error updating task. Please try again.');
      } finally {
        setTaskActionId(null);
      }
    },
    [appendMessage, refreshTasks, sessionId, taskNotes]
  );

  const handleConfirmDate = useCallback(
    async (date: string, messageId: string) => {
      if (!sessionId || !date) {
        return;
      }
      setIsLoading(true);
      try {
        const reply = await fetchWorkflowReply(`${API_BASE}/conversation/${sessionId}/confirm-date`, {
          date,
        });
        updateMessageAt(messageId, (msg) => {
          if (!msg.meta?.confirmDate) {
            return msg;
          }
          const nextMeta = { ...msg.meta };
          delete nextMeta.confirmDate;
          return { ...msg, meta: Object.keys(nextMeta).length ? nextMeta : undefined };
        });
        const assistantId = appendMessage({
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          streaming: true,
        });
        await handleAssistantReply(assistantId, reply);
      } catch (error) {
        console.error('Error confirming date:', error);
        alert('Error confirming date. Please try again.');
      } finally {
        setIsLoading(false);
      }
    },
    [appendMessage, handleAssistantReply, sessionId, updateMessageAt]
  );

  const handleChangeDate = useCallback(
    (messageId: string) => {
      appendMessage({
        role: 'assistant',
        content: 'No problem - please share another date that works for you.',
        timestamp: new Date(),
      });
      updateMessageAt(messageId, (msg) => {
        if (!msg.meta?.confirmDate) {
          return msg;
        }
        const nextMeta = { ...msg.meta };
        delete nextMeta.confirmDate;
        return { ...msg, meta: Object.keys(nextMeta).length ? nextMeta : undefined };
      });
    },
    [appendMessage, updateMessageAt]
  );

  const acceptBooking = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    try {
      const response = await requestJSON<{ filename: string }>(`${API_BASE}/accept-booking/${sessionId}`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      alert(`✅ Booking accepted! Saved to: ${response.filename}`);
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
    } catch (error) {
      console.error('Error accepting booking:', error);
      alert('Error accepting booking');
    }
  }, [sessionId]);

  const rejectBooking = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    try {
      await requestJSON(`${API_BASE}/reject-booking/${sessionId}`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      alert('❌ Booking rejected');
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
    } catch (error) {
      console.error('Error rejecting booking:', error);
      alert('Error rejecting booking');
    }
  }, [sessionId]);

  const handleKeyPress = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!hasStarted) {
          startConversation().catch(() => undefined);
        } else {
          sendMessage().catch(() => undefined);
        }
      }
    },
    [hasStarted, sendMessage, startConversation]
  );

  const visibleMessages = useMemo(() => {
    const sliceStart = Math.max(0, messages.length - 60);
    return messages.slice(sliceStart);
  }, [messages]);

  const messageOffset = messages.length - visibleMessages.length;

  const assistantTyping = useMemo(() => isLoading || messages.some((msg) => msg.streaming), [isLoading, messages]);

  const filteredEventInfo = useMemo(() => {
    if (!eventInfo || !isComplete) {
      return [] as Array<[string, string]>;
    }
    return Object.entries(eventInfo).filter(([key, value]) => shouldDisplayEventField(key, value));
  }, [eventInfo, isComplete]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-4">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-t-2xl shadow-lg p-6 border-b">
          <h1 className="text-3xl font-bold text-gray-800 flex items-center gap-3">
            🎭 OpenEvent - AI Event Manager
          </h1>
          <p className="text-gray-600 mt-2">
            {!hasStarted
              ? 'Paste a client email below to start the conversation'
              : 'Conversation in progress with Shami, Event Manager'}
          </p>
          {workflowType && (
            <div className="mt-2 inline-block">
              <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                Workflow: {workflowType}
              </span>
            </div>
          )}
        </div>

        {backendHealthy === false && (
          <div className="mt-2 p-3 bg-red-50 border border-red-300 text-red-700 rounded">
            Backend unreachable: {backendError || `Failed to fetch ${API_BASE}`} — please ensure the server is running and NEXT_PUBLIC_BACKEND_BASE is correct.
          </div>
        )}

        <div
          ref={threadRef}
          className="bg-white shadow-lg"
          style={{ minHeight: '500px', maxHeight: '600px', overflowY: 'auto' }}
          onScroll={(event) => handleThreadScroll(event.currentTarget)}
        >
          <div className="p-6 space-y-6">
            {visibleMessages.length === 0 && (
              <div className="text-center py-12 text-gray-400">
                <p className="text-lg">No messages yet...</p>
                <p className="text-sm mt-2">Start by pasting a client inquiry email below</p>
              </div>
            )}

            {visibleMessages.map((msg, idx) => {
              const absoluteIndex = messageOffset + idx;
              return (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                    <div
                      className={`text-xs font-semibold mb-1 ${
                        msg.role === 'user' ? 'text-right text-blue-600' : 'text-left text-gray-600'
                      }`}
                    >
                      {msg.role === 'user' ? '👤 Client' : '🎭 Shami (Event Manager)'}
                    </div>
                    <div
                      className={`rounded-2xl px-4 py-3 shadow-sm ${
                        msg.role === 'user'
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-100 text-gray-800 border border-gray-200'
                      } ${msg.streaming ? 'animate-pulse' : ''}`}
                    >
                      <div className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</div>
                      {msg.role === 'assistant' && msg.meta?.confirmDate && (
                        <div className="flex gap-2 mt-3">
                          <button
                            onClick={() => handleConfirmDate(msg.meta?.confirmDate ?? '', msg.id)}
                            disabled={isLoading || !sessionId}
                            className="px-3 py-1 text-xs font-semibold rounded bg-green-600 text-white disabled:bg-gray-300 disabled:cursor-not-allowed"
                          >
                            Confirm date
                          </button>
                          <button
                            onClick={() => handleChangeDate(msg.id)}
                            disabled={isLoading}
                            className="px-3 py-1 text-xs font-semibold rounded border border-gray-400 text-gray-700 hover:bg-gray-200 disabled:cursor-not-allowed"
                          >
                            Change date
                          </button>
                        </div>
                      )}
                      <div className={`${msg.role === 'user' ? 'text-blue-100' : 'text-gray-500'} text-xs mt-2`}>
                        {msg.timestamp.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}

            {assistantTyping && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-2xl px-4 py-3 border border-gray-200">
                  <div className="flex items-center gap-2 text-gray-600">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">Shami is typing...</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {isComplete && (
          <div className="bg-gradient-to-r from-green-50 to-blue-50 p-6 border-t border-gray-200">
            <div className="text-center mb-4">
              <p className="text-lg font-semibold text-gray-800">✅ Ready to finalize your booking!</p>
              <p className="text-sm text-gray-600 mt-1">
                Click Accept to save this booking to our system, or Reject to discard.
              </p>
            </div>
            <div className="flex gap-4 justify-center">
              <button
                onClick={acceptBooking}
                disabled={isLoading}
                className="flex items-center gap-2 px-8 py-4 bg-green-500 hover:bg-green-600 disabled:bg-gray-300 text-white rounded-xl font-bold text-lg shadow-lg transition-all transform hover:scale-105 disabled:cursor-not-allowed"
              >
                <CheckCircle className="w-6 h-6" />
                Accept & Save Booking
              </button>
              <button
                onClick={rejectBooking}
                disabled={isLoading}
                className="flex items-center gap-2 px-8 py-4 bg-red-500 hover:bg-red-600 disabled:bg-gray-300 text-white rounded-xl font-bold text-lg shadow-lg transition-all transform hover:scale-105 disabled:cursor-not-allowed"
              >
                <XCircle className="w-6 h-6" />
                Reject & Discard
              </button>
            </div>
          </div>
        )}

        <div className="bg-white rounded-b-2xl shadow-lg p-4 border-t">
          <div className="flex gap-3">
            <textarea
              value={draftInput}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={!hasStarted ? "Paste the client's email here to start..." : 'Type your response as the client...'}
              className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              rows={3}
              disabled={isLoading || isComplete}
            />
            <button
              onClick={!hasStarted ? () => startConversation().catch(() => undefined) : () => sendMessage().catch(() => undefined)}
              disabled={isLoading || isComplete || !draftInput.trim()}
              className="px-6 py-3 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white rounded-xl font-semibold shadow-md transition-all flex items-center gap-2 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="w-5 h-5" />
                  Send
                </>
              )}
            </button>
          </div>
          <div className="text-xs text-gray-500 mt-2">Press Enter to send • Shift+Enter for new line</div>
        </div>

        {filteredEventInfo.length > 0 && (
          <div className="mt-4 bg-white rounded-2xl shadow-lg p-6">
            <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">📋 Information Collected So Far</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              {filteredEventInfo.map(([key, value]) => (
                <div key={key} className="flex flex-col">
                  <span className="text-gray-600 text-xs uppercase tracking-wide">{key.replace(/_/g, ' ')}</span>
                  <span className="font-semibold text-gray-800 mt-1">{value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="max-w-4xl mx-auto mt-4 p-4 bg-yellow-50 border-2 border-yellow-400 rounded-lg">
        <h3 className="font-bold text-lg mb-2">🐛 DEBUG INFO</h3>
        <div className="grid grid-cols-2 gap-2 text-sm font-mono">
          <div>
            sessionId: <span className="font-bold">{sessionId || 'null'}</span>
          </div>
          <div>
            isComplete: <span className="font-bold text-red-600">{isComplete ? 'TRUE' : 'FALSE'}</span>
          </div>
          <div>
            isLoading: <span className="font-bold">{isLoading ? 'TRUE' : 'FALSE'}</span>
          </div>
          <div>
            hasStarted: <span className="font-bold">{hasStarted ? 'TRUE' : 'FALSE'}</span>
          </div>
          <div>
            workflowType: <span className="font-bold">{workflowType || 'null'}</span>
          </div>
          <div>
            messages: <span className="font-bold">{messages.length}</span>
          </div>
          <div>
            debouncedInputLength: <span className="font-bold">{inputText.trim().length}</span>
          </div>
        </div>
        <div className="mt-2 p-2 bg-white rounded">
          <strong>Should show buttons?</strong> {isComplete ? '✅ YES' : '❌ NO'}
        </div>
      </div>

      <div className="max-w-4xl mx-auto mt-2">
        <div className="p-3 bg-white border border-gray-200 rounded-lg shadow-sm">
          <h3 className="font-bold text-base mb-2">📝 Tasks</h3>
          {tasks.length === 0 ? (
            <p className="text-xs text-gray-500">No pending tasks.</p>
          ) : (
            <div className="space-y-2">
              {tasks.map((task) => {
                const suggestedDates = Array.isArray(task.payload?.suggested_dates)
                  ? task.payload!.suggested_dates!.filter((date): date is string => Boolean(date))
                  : [];
                return (
                  <div key={task.task_id} className="p-3 bg-gray-50 border border-gray-200 rounded-md">
                    <div className="text-sm font-semibold text-gray-800">{task.type}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      Client: {task.client_id || 'unknown'} | Created:{' '}
                      {task.created_at ? new Date(task.created_at).toLocaleString() : 'n/a'}
                    </div>
                    {suggestedDates.length > 0 && (
                      <div className="text-xs text-gray-700 mt-2">Suggested dates: {suggestedDates.join(', ')}</div>
                    )}
                    {task.payload?.snippet && (
                      <div className="text-xs text-gray-600 mt-1 italic">"{task.payload.snippet}"</div>
                    )}
                    {(task.type === 'ask_for_date' || task.type === 'manual_review') && (
                      <>
                        <div className="mt-2">
                          <textarea
                            value={taskNotes[task.task_id] || ''}
                            onChange={(e) =>
                              setTaskNotes((prev) => ({ ...prev, [task.task_id!]: e.target.value }))
                            }
                            placeholder="Optional manager notes (sent with decision)"
                            className="w-full text-xs p-2 border border-gray-300 rounded-md"
                            rows={2}
                          />
                        </div>
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={() => handleTaskAction(task, 'approve')}
                            disabled={taskActionId === task.task_id}
                            title="Approve"
                            className="px-3 py-1 text-xs font-semibold rounded bg-green-600 text-white disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-1"
                          >
                            {taskActionId === task.task_id ? 'Saving...' : 'Approve'}
                          </button>
                          <button
                            onClick={() => handleTaskAction(task, 'reject')}
                            disabled={taskActionId === task.task_id}
                            title="Reject"
                            className="px-3 py-1 text-xs font-semibold rounded border border-gray-400 text-gray-700 hover:bg-gray-200 disabled:cursor-not-allowed flex items-center gap-1"
                          >
                            {taskActionId === task.task_id ? 'Saving...' : 'Reject'}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

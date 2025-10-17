'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

interface MessageMeta {
  confirmDate?: string;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  meta?: MessageMeta;
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

export default function EmailThreadUI() {
  const isMountedRef = useRef(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [eventInfo, setEventInfo] = useState<EventInfo | null>(null);
  const [workflowType, setWorkflowType] = useState<string | null>(null);
  const [tasks, setTasks] = useState<PendingTask[]>([]);
  const [taskActionId, setTaskActionId] = useState<string | null>(null);
  
  // Initial state - waiting for first email
  const [hasStarted, setHasStarted] = useState(false);

  const refreshTasks = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/tasks/pending`);
      if (!isMountedRef.current) {
        return;
      }
      if (Array.isArray(data.tasks)) {
        setTasks(data.tasks);
      } else {
        setTasks([]);
      }
    } catch (error) {
      if (isMountedRef.current) {
        console.error('Error fetching tasks:', error);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    refreshTasks().catch(() => undefined);
    const interval = setInterval(() => {
      refreshTasks().catch(() => undefined);
    }, 5000);

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
    };
  }, [refreshTasks]);

  const startConversation = async () => {
    if (!inputText.trim()) return;
    
    setIsLoading(true);
    
    // Extract email from input text
    const extractEmail = (text: string): string => {
      const emailRegex = /[\w.-]+@[\w.-]+\.\w+/;
      const match = text.match(emailRegex);
      return match ? match[0] : 'unknown@example.com';
    };
    
    try {
      const response = await axios.post(`${API_BASE}/start-conversation`, {
        email_body: inputText,
        client_email: extractEmail(inputText) // ✅ Extract from text
      });
      
      const { session_id, workflow_type, response: aiResponse, is_complete, event_info, pending_actions } = response.data;

      const userMessage: Message = { role: 'user', content: inputText, timestamp: new Date() };
      let assistantMeta: MessageMeta | undefined;
      if (pending_actions?.type === 'confirm_date' && typeof pending_actions.date === 'string') {
        assistantMeta = { confirmDate: pending_actions.date };
      }
      const assistantMessage: Message = {
        role: 'assistant',
        content: aiResponse,
        timestamp: new Date(),
        meta: assistantMeta,
      };
      
      // If not a new event, show message and stop
      if (!session_id) {
        setMessages([userMessage, assistantMessage]);
        setInputText('');
        setIsLoading(false);
        return;
      }
      
      setSessionId(session_id);
      setWorkflowType(workflow_type);
      setHasStarted(true);
      
      setMessages([userMessage, assistantMessage]);
      
      setIsComplete(is_complete);
      setEventInfo(event_info);
      setInputText('');
      refreshTasks();
      
    } catch (error) {
      console.error('Error starting conversation:', error);
      alert('Error connecting to server. Make sure backend is running on port 8000.');
    }
    
    setIsLoading(false);
  };

  const sendMessage = async () => {
    if (!inputText.trim() || !sessionId) return;
    
    setIsLoading(true);
    
    // Add user message immediately
    const userMessage: Message = {
      role: 'user',
      content: inputText,
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMessage]);
    const currentInput = inputText;
    setInputText('');
    
    try {
      const response = await axios.post(`${API_BASE}/send-message`, {
        session_id: sessionId,
        message: currentInput
      });
      
      const { response: aiResponse, is_complete, event_info, pending_actions } = response.data;
      
      // Add AI response
      let assistantMeta: MessageMeta | undefined;
      if (pending_actions?.type === 'confirm_date' && typeof pending_actions.date === 'string') {
        assistantMeta = { confirmDate: pending_actions.date };
      }
      const aiMessage: Message = {
        role: 'assistant',
        content: aiResponse,
        timestamp: new Date(),
        meta: assistantMeta
      };
      setMessages(prev => [...prev, aiMessage]);
      
      // Update state
      setIsComplete(is_complete);
      setEventInfo(event_info);
      
      console.log('Is Complete:', is_complete); // Debug log
      
    } catch (error) {
      console.error('Error sending message:', error);
      alert('Error sending message');
    }
    
    setIsLoading(false);
  };

  const handleTaskAction = async (task: PendingTask, decision: 'approve' | 'reject') => {
    if (!task.task_id) return;
    setTaskActionId(task.task_id);
    try {
      await axios.post(`${API_BASE}/tasks/${task.task_id}/${decision}`, {});
      const assistantContent =
        decision === 'approve'
          ? "I've proposed these dates to the client. Please pick one."
          : "I won't send the date suggestion yet.";
      if (sessionId) {
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: assistantContent,
            timestamp: new Date(),
          },
        ]);
      }
      await refreshTasks();
    } catch (error) {
      console.error(`Error updating task (${decision}):`, error);
      alert('Error updating task. Please try again.');
    } finally {
      setTaskActionId(null);
    }
  };

  const handleConfirmDate = async (date: string, messageIndex: number) => {
    if (!sessionId || !date) return;
    setIsLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/conversation/${sessionId}/confirm-date`, {
        date,
      });
      const { response: aiResponse, is_complete, event_info, pending_actions } = response.data;
      let assistantMeta: MessageMeta | undefined;
      if (pending_actions?.type === 'confirm_date' && typeof pending_actions.date === 'string') {
        assistantMeta = { confirmDate: pending_actions.date };
      }
      const assistantMessage: Message = {
        role: 'assistant',
        content: aiResponse,
        timestamp: new Date(),
        meta: assistantMeta,
      };
      setMessages(prev => {
        const updated = prev.map((msg, idx) => {
          if (idx !== messageIndex) return msg;
          if (!msg.meta?.confirmDate) return msg;
          const nextMeta = { ...msg.meta };
          delete nextMeta.confirmDate;
          return {
            ...msg,
            meta: Object.keys(nextMeta).length ? nextMeta : undefined,
          };
        });
        return [...updated, assistantMessage];
      });
      setIsComplete(is_complete);
      setEventInfo(event_info);
    } catch (error) {
      console.error('Error confirming date:', error);
      alert('Error confirming date. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleChangeDate = (messageIndex: number) => {
    setMessages(prev => {
      const updated = prev.map((msg, idx) => {
        if (idx !== messageIndex) return msg;
        if (!msg.meta?.confirmDate) return msg;
        return { ...msg, meta: undefined };
      });
      return [
        ...updated,
        {
          role: 'assistant',
          content: 'No problem - please share another date that works for you.',
          timestamp: new Date(),
        },
      ];
    });
  };

  const acceptBooking = async () => {
    if (!sessionId) return;
    
    try {
      const response = await axios.post(`${API_BASE}/accept-booking/${sessionId}`);
      alert(`✅ Booking accepted! Saved to: ${response.data.filename}`);
      
      // Reset
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
      
    } catch (error) {
      console.error('Error accepting booking:', error);
      alert('Error accepting booking');
    }
  };

  const rejectBooking = async () => {
    if (!sessionId) return;
    
    try {
      await axios.post(`${API_BASE}/reject-booking/${sessionId}`);
      alert('❌ Booking rejected');
      
      // Reset
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
      
    } catch (error) {
      console.error('Error rejecting booking:', error);
      alert('Error rejecting booking');
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!hasStarted) {
        startConversation();
      } else {
        sendMessage();
      }
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-4">
      <div className="max-w-4xl mx-auto">
        
        {/* Header */}
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

        {/* Email Thread / Chat Area */}
        <div className="bg-white shadow-lg" style={{ minHeight: '500px', maxHeight: '600px', overflowY: 'auto' }}>
          <div className="p-6 space-y-6">
            
            {messages.length === 0 && (
              <div className="text-center py-12 text-gray-400">
                <p className="text-lg">No messages yet...</p>
                <p className="text-sm mt-2">Start by pasting a client inquiry email below</p>
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                  
                  {/* Sender Label */}
                  <div className={`text-xs font-semibold mb-1 ${
                    msg.role === 'user' ? 'text-right text-blue-600' : 'text-left text-gray-600'
                  }`}>
                    {msg.role === 'user' ? '👤 Client' : '🎭 Shami (Event Manager)'}
                  </div>
                  
                  {/* Message Bubble */}
                  <div className={`rounded-2xl px-4 py-3 shadow-sm ${
                    msg.role === 'user' 
                      ? 'bg-blue-500 text-white' 
                      : 'bg-gray-100 text-gray-800 border border-gray-200'
                  }`}>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed">
                      {msg.content}
                    </div>
                    {msg.role === 'assistant' && msg.meta?.confirmDate && (
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={() => handleConfirmDate(msg.meta?.confirmDate ?? '', idx)}
                          disabled={isLoading || !sessionId}
                          className="px-3 py-1 text-xs font-semibold rounded bg-green-600 text-white disabled:bg-gray-300 disabled:cursor-not-allowed"
                        >
                          Confirm date
                        </button>
                        <button
                          onClick={() => handleChangeDate(idx)}
                          disabled={isLoading}
                          className="px-3 py-1 text-xs font-semibold rounded border border-gray-400 text-gray-700 hover:bg-gray-200 disabled:cursor-not-allowed"
                        >
                          Change date
                        </button>
                      </div>
                    )}
                    <div className={`text-xs mt-2 ${
                      msg.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                    }`}>
                      {msg.timestamp.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {isLoading && (
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

        {/* Accept/Reject Buttons - Show when complete */}
        {isComplete && (
          <div className="bg-gradient-to-r from-green-50 to-blue-50 p-6 border-t border-gray-200">
            <div className="text-center mb-4">
              <p className="text-lg font-semibold text-gray-800">
                ✅ Ready to finalize your booking!
              </p>
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

        {/* Input Area */}
        <div className="bg-white rounded-b-2xl shadow-lg p-4 border-t">
          <div className="flex gap-3">
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={!hasStarted 
                ? "Paste the client's email here to start..." 
                : "Type your response as the client..."}
              className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              rows={3}
              disabled={isLoading || isComplete}
            />
            
            <button
              onClick={!hasStarted ? startConversation : sendMessage}
              disabled={isLoading || isComplete || !inputText.trim()}
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
          
          <div className="text-xs text-gray-500 mt-2">
            Press Enter to send • Shift+Enter for new line
          </div>
        </div>

        {/* Event Info Panel - ONLY show when complete */}
        {eventInfo && isComplete && (
          <div className="mt-4 bg-white rounded-2xl shadow-lg p-6">
            <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
              📋 Information Collected So Far
            </h3>
            
            <div className="grid grid-cols-2 gap-3 text-sm">
              {Object.entries(eventInfo).map(([key, value]) => {
                // Skip "Not specified", "none", and room status fields
                if (value === 'Not specified' || 
                    value === 'none' || 
                    key === 'room_a_status' || 
                    key === 'room_b_status' || 
                    key === 'room_c_status') {
                  return null;
                }
                
                return (
                  <div key={key} className="flex flex-col">
                    <span className="text-gray-600 text-xs uppercase tracking-wide">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <span className="font-semibold text-gray-800 mt-1">
                      {value}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

      </div>
      {/* DEBUG PANEL - Add this right after the main container */}
      <div className="max-w-4xl mx-auto mt-4 p-4 bg-yellow-50 border-2 border-yellow-400 rounded-lg">
        <h3 className="font-bold text-lg mb-2">🐛 DEBUG INFO</h3>
        <div className="grid grid-cols-2 gap-2 text-sm font-mono">
          <div>sessionId: <span className="font-bold">{sessionId || 'null'}</span></div>
          <div>isComplete: <span className="font-bold text-red-600">{isComplete ? 'TRUE' : 'FALSE'}</span></div>
          <div>isLoading: <span className="font-bold">{isLoading ? 'TRUE' : 'FALSE'}</span></div>
          <div>hasStarted: <span className="font-bold">{hasStarted ? 'TRUE' : 'FALSE'}</span></div>
          <div>workflowType: <span className="font-bold">{workflowType || 'null'}</span></div>
          <div>messages: <span className="font-bold">{messages.length}</span></div>
        </div>
        
        {/* Show what buttons condition evaluates to */}
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
                    <div className="text-sm font-semibold text-gray-800">
                      {task.type}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      Client: {task.client_id || 'unknown'} | Created: {task.created_at ? new Date(task.created_at).toLocaleString() : 'n/a'}
                    </div>
                    {suggestedDates.length > 0 && (
                      <div className="text-xs text-gray-700 mt-2">
                        Suggested dates: {suggestedDates.join(', ')}
                      </div>
                    )}
                    {task.payload?.snippet && (
                      <div className="text-xs text-gray-600 mt-1 italic">
                        &quot;{task.payload.snippet}&quot;
                      </div>
                    )}
                    {task.type === 'ask_for_date' && (
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={() => handleTaskAction(task, 'approve')}
                          disabled={taskActionId === task.task_id}
                          className="px-3 py-1 text-xs font-semibold rounded bg-green-600 text-white disabled:bg-gray-300 disabled:cursor-not-allowed"
                        >
                          {taskActionId === task.task_id ? 'Saving...' : 'Approve'}
                        </button>
                        <button
                          onClick={() => handleTaskAction(task, 'reject')}
                          disabled={taskActionId === task.task_id}
                          className="px-3 py-1 text-xs font-semibold rounded border border-gray-400 text-gray-700 hover:bg-gray-200 disabled:cursor-not-allowed"
                        >
                          {taskActionId === task.task_id ? 'Saving...' : 'Reject'}
                        </button>
                      </div>
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

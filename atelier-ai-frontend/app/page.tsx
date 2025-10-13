'use client';

import { useState } from 'react';
import { Send, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface EventInfo {
  [key: string]: string;
}

export default function EmailThreadUI() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [eventInfo, setEventInfo] = useState<EventInfo | null>(null);
  const [workflowType, setWorkflowType] = useState<string | null>(null);
  
  // Initial state - waiting for first email
  const [hasStarted, setHasStarted] = useState(false);

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
      
      const { session_id, workflow_type, response: aiResponse, is_complete, event_info } = response.data;
      
      // If not a new event, show message and stop
      if (!session_id) {
        setMessages([
          { role: 'user', content: inputText, timestamp: new Date() },
          { role: 'assistant', content: aiResponse, timestamp: new Date() }
        ]);
        setInputText('');
        setIsLoading(false);
        return;
      }
      
      setSessionId(session_id);
      setWorkflowType(workflow_type);
      setHasStarted(true);
      
      setMessages([
        { role: 'user', content: inputText, timestamp: new Date() },
        { role: 'assistant', content: aiResponse, timestamp: new Date() }
      ]);
      
      setIsComplete(is_complete);
      setEventInfo(event_info);
      setInputText('');
      
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
      
      const { response: aiResponse, is_complete, event_info } = response.data;
      
      // Add AI response
      const aiMessage: Message = {
        role: 'assistant',
        content: aiResponse,
        timestamp: new Date()
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
    </div>
  );
}
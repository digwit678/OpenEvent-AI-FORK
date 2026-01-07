'use client';

import { useState, useCallback } from 'react';

/**
 * CancelEventButton Component
 *
 * Allows managers to cancel an event booking with confirmation.
 * Requires typing "CANCEL" to prevent accidental cancellations.
 *
 * Different handling based on event state:
 * - Site visit scheduled: Manager should send regret email after cancelling
 * - Standard flow: Event is archived immediately
 *
 * See docs/plans/OPEN_DECISIONS.md DECISION-012 for details.
 */

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

interface CancelEventButtonProps {
  /** The event ID to cancel */
  eventId: string;
  /** Whether the event has a site visit scheduled */
  hasSiteVisit?: boolean;
  /** Current workflow step */
  currentStep?: number;
  /** Callback when event is successfully cancelled */
  onCancel?: (result: CancelResult) => void;
  /** Compact mode (just shows button, dialog on click) */
  compact?: boolean;
  /** Use dark theme (for debug pages) */
  darkTheme?: boolean;
}

interface CancelResult {
  status: string;
  event_id: string;
  previous_step: number;
  had_site_visit: boolean;
  cancellation_type: string;
  archived_at: string;
}

export default function CancelEventButton({
  eventId,
  hasSiteVisit = false,
  currentStep,
  onCancel,
  compact = true,
  darkTheme = false,
}: CancelEventButtonProps) {
  const [showDialog, setShowDialog] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [reason, setReason] = useState('');
  const [isCancelling, setIsCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CancelResult | null>(null);

  const isConfirmValid = confirmText === 'CANCEL';

  const handleCancel = useCallback(async () => {
    if (!isConfirmValid) return;

    setIsCancelling(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/event/${eventId}/cancel`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          event_id: eventId,
          confirmation: 'CANCEL',
          reason: reason || undefined,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Failed to cancel event' }));
        throw new Error(data.detail || 'Failed to cancel event');
      }

      const data: CancelResult = await response.json();
      setResult(data);

      if (onCancel) {
        onCancel(data);
      }

      // Close dialog after short delay to show success
      setTimeout(() => {
        setShowDialog(false);
        setConfirmText('');
        setReason('');
        setResult(null);
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel event');
    } finally {
      setIsCancelling(false);
    }
  }, [eventId, isConfirmValid, reason, onCancel]);

  const handleClose = useCallback(() => {
    if (isCancelling) return;
    setShowDialog(false);
    setConfirmText('');
    setReason('');
    setError(null);
    setResult(null);
  }, [isCancelling]);

  // Theme-aware styles
  const buttonStyle = darkTheme
    ? "px-3 py-1.5 text-xs font-medium text-red-400 hover:text-red-300 hover:bg-red-500/20 border border-red-500/30 rounded transition"
    : "px-3 py-1.5 text-xs font-medium text-red-600 hover:text-red-800 hover:bg-red-50 border border-red-300 rounded transition";

  const dialogBgStyle = darkTheme
    ? "bg-slate-800 border border-slate-700"
    : "bg-white";

  const textStyle = darkTheme
    ? "text-slate-100"
    : "text-gray-800";

  const mutedTextStyle = darkTheme
    ? "text-slate-400"
    : "text-gray-500";

  const inputStyle = darkTheme
    ? "bg-slate-700 border-slate-600 text-slate-100 placeholder-slate-400"
    : "border-gray-300";

  return (
    <>
      {/* Trigger Button */}
      <button
        onClick={() => setShowDialog(true)}
        className={buttonStyle}
        title="Cancel this event"
      >
        Cancel Event
      </button>

      {/* Confirmation Dialog */}
      {showDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={handleClose}
          role="presentation"
        >
          <div
            className={`${dialogBgStyle} rounded-lg shadow-xl max-w-md w-full mx-4`}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="cancel-dialog-title"
          >
            {/* Header */}
            <div className={`p-4 border-b ${darkTheme ? 'border-slate-700' : 'border-gray-200'}`}>
              <h2 id="cancel-dialog-title" className={`text-lg font-semibold ${textStyle}`}>
                Cancel Event
              </h2>
              <p className={`text-sm ${mutedTextStyle} mt-1`}>
                This action cannot be undone. The event will be archived.
              </p>
            </div>

            {/* Content */}
            <div className="p-4 space-y-4">
              {/* Warning for site visit */}
              {hasSiteVisit && (
                <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <span className="text-yellow-600">⚠️</span>
                    <div>
                      <div className="font-medium text-yellow-800 text-sm">
                        Site Visit Was Scheduled
                      </div>
                      <div className="text-yellow-700 text-xs mt-1">
                        Please send a regret email to the client after cancelling.
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Error message */}
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded">
                  {error}
                </div>
              )}

              {/* Success message */}
              {result && (
                <div className="p-3 bg-green-50 border border-green-200 text-green-700 text-sm rounded">
                  Event cancelled successfully.
                  {result.had_site_visit && ' Remember to send a regret email to the client.'}
                </div>
              )}

              {!result && (
                <>
                  {/* Reason (optional) */}
                  <div>
                    <label htmlFor="cancel-reason" className={`block text-sm font-medium ${darkTheme ? 'text-slate-300' : 'text-gray-700'} mb-1`}>
                      Reason for cancellation (optional)
                    </label>
                    <textarea
                      id="cancel-reason"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Client requested cancellation..."
                      rows={2}
                      className={`w-full px-3 py-2 text-sm border rounded focus:ring-2 focus:ring-red-500 focus:border-red-500 ${inputStyle}`}
                      disabled={isCancelling}
                    />
                  </div>

                  {/* Confirmation input */}
                  <div>
                    <label htmlFor="cancel-confirm" className={`block text-sm font-medium ${darkTheme ? 'text-slate-300' : 'text-gray-700'} mb-1`}>
                      Type <span className={`font-mono px-1 rounded ${darkTheme ? 'bg-slate-600' : 'bg-gray-100'}`}>CANCEL</span> to confirm
                    </label>
                    <input
                      id="cancel-confirm"
                      type="text"
                      value={confirmText}
                      onChange={(e) => setConfirmText(e.target.value)}
                      placeholder="CANCEL"
                      className={`w-full px-3 py-2 text-sm border rounded focus:ring-2 focus:ring-red-500 focus:border-red-500 font-mono ${
                        confirmText && !isConfirmValid
                          ? darkTheme ? 'border-red-500/50 bg-red-500/10' : 'border-red-300 bg-red-50'
                          : isConfirmValid
                          ? darkTheme ? 'border-green-500/50 bg-green-500/10' : 'border-green-300 bg-green-50'
                          : inputStyle
                      }`}
                      disabled={isCancelling}
                      autoComplete="off"
                    />
                    {confirmText && !isConfirmValid && (
                      <p className="text-xs text-red-500 mt-1">
                        Please type CANCEL exactly (case-sensitive)
                      </p>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Footer */}
            <div className={`p-4 border-t ${darkTheme ? 'border-slate-700' : 'border-gray-200'} flex gap-2`}>
              <button
                onClick={handleClose}
                disabled={isCancelling}
                className={`flex-1 px-4 py-2 text-sm font-medium rounded transition disabled:opacity-50 ${
                  darkTheme
                    ? 'text-slate-300 bg-slate-700 border border-slate-600 hover:bg-slate-600'
                    : 'text-gray-700 bg-white border border-gray-300 hover:bg-gray-50'
                }`}
              >
                {result ? 'Close' : 'Back'}
              </button>
              {!result && (
                <button
                  onClick={handleCancel}
                  disabled={!isConfirmValid || isCancelling}
                  className="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-500 rounded hover:bg-red-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isCancelling ? 'Cancelling...' : 'Cancel Event'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

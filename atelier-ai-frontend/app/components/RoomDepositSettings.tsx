'use client';

/**
 * RoomDepositSettings Component (INACTIVE - For Future Integration)
 *
 * INTEGRATION NOTE FOR FRONTEND INTEGRATORS:
 * ==========================================
 * This component is prepared for future integration with the main OpenEvent
 * frontend. It allows setting deposit requirements per room, which override
 * the global deposit setting.
 *
 * To activate this component:
 * 1. Import it in the Rooms Setup page
 * 2. Uncomment the backend endpoints in backend/main.py:
 *    - GET /api/config/room-deposit/{room_id}
 *    - POST /api/config/room-deposit/{room_id}
 * 3. Add the component to each room card or a room settings modal
 *
 * Data structure matches the real frontend:
 * {
 *   room_id: string,
 *   deposit_required: boolean,
 *   deposit_percent: number (1-100) | null,
 *   updated_at: ISO timestamp
 * }
 *
 * This file is NOT imported anywhere in the current codebase to keep it inactive.
 * Search for "RoomDepositSettings" when ready to integrate.
 */

import { useState, useCallback } from 'react';

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

export interface RoomDepositConfig {
  room_id: string;
  deposit_required: boolean;
  deposit_percent: number | null;
  updated_at?: string;
}

interface RoomDepositSettingsProps {
  /** The room ID to configure deposit for */
  roomId: string;
  /** Room name for display */
  roomName: string;
  /** Initial config values (optional) */
  initialConfig?: Partial<RoomDepositConfig>;
  /** Callback when deposit settings are saved */
  onSave?: (config: RoomDepositConfig) => void;
  /** Show in inline mode (compact display) */
  inline?: boolean;
}

export default function RoomDepositSettings({
  roomId,
  roomName,
  initialConfig,
  onSave,
  inline = false,
}: RoomDepositSettingsProps) {
  const [depositRequired, setDepositRequired] = useState(
    initialConfig?.deposit_required ?? false
  );
  const [depositPercent, setDepositPercent] = useState<number | null>(
    initialConfig?.deposit_percent ?? null
  );
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);

    try {
      // NOTE: This endpoint is currently commented out in the backend.
      // Uncomment the endpoint in backend/main.py before using.
      const response = await fetch(`${API_BASE}/config/room-deposit/${roomId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          deposit_required: depositRequired,
          deposit_percent: depositRequired ? depositPercent : null,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to save room deposit settings');
      }

      const result = await response.json();
      setIsEditing(false);

      if (onSave) {
        onSave({
          room_id: roomId,
          deposit_required: depositRequired,
          deposit_percent: depositRequired ? depositPercent : null,
          updated_at: result.config?.updated_at,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }, [roomId, depositRequired, depositPercent, onSave]);

  if (inline) {
    // Inline mode - minimal display for room cards
    return (
      <div className="flex items-center gap-2 text-xs">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={depositRequired}
            onChange={(e) => setDepositRequired(e.target.checked)}
            className="h-3 w-3"
          />
          <span className="text-gray-600">Deposit</span>
        </label>
        {depositRequired && (
          <input
            type="number"
            min="1"
            max="100"
            value={depositPercent ?? ''}
            onChange={(e) => setDepositPercent(e.target.value ? parseInt(e.target.value) : null)}
            placeholder="%"
            className="w-12 px-1 py-0.5 text-xs border border-gray-300 rounded"
          />
        )}
      </div>
    );
  }

  return (
    <div className="p-3 bg-gray-50 rounded-lg border border-gray-200">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-medium text-gray-700">
          Deposit for {roomName}
        </h4>
        {!isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            Edit
          </button>
        )}
      </div>

      {error && (
        <div className="mb-2 p-2 bg-red-50 border border-red-200 text-red-700 text-xs rounded">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {/* Deposit Required Toggle */}
        <div className="flex items-center justify-between">
          <label htmlFor={`deposit-required-${roomId}`} className="text-sm text-gray-600">
            Require deposit for this room
          </label>
          <button
            id={`deposit-required-${roomId}`}
            type="button"
            role="switch"
            aria-checked={depositRequired}
            disabled={!isEditing}
            onClick={() => setDepositRequired(!depositRequired)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              depositRequired ? 'bg-blue-500' : 'bg-gray-300'
            } ${!isEditing ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span
              className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                depositRequired ? 'translate-x-5' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {/* Deposit Percentage */}
        {depositRequired && (
          <div>
            <label
              htmlFor={`deposit-percent-${roomId}`}
              className="block text-sm text-gray-600 mb-1"
            >
              Deposit percentage (%)
            </label>
            <input
              id={`deposit-percent-${roomId}`}
              type="number"
              min="1"
              max="100"
              value={depositPercent ?? ''}
              onChange={(e) =>
                setDepositPercent(e.target.value ? parseInt(e.target.value) : null)
              }
              disabled={!isEditing}
              placeholder="e.g. 30"
              className={`w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 ${
                !isEditing ? 'bg-gray-100 cursor-not-allowed' : ''
              }`}
            />
            <p className="text-xs text-gray-500 mt-1">
              Overrides the global deposit setting for offers using this room.
            </p>
          </div>
        )}

        {/* Action Buttons */}
        {isEditing && (
          <div className="flex gap-2 pt-2 border-t border-gray-200">
            <button
              onClick={() => setIsEditing(false)}
              disabled={isSaving}
              className="flex-1 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 transition disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex-1 px-3 py-1.5 text-xs font-medium text-white bg-blue-500 rounded hover:bg-blue-600 transition disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


/**
 * Example usage in a Rooms page:
 *
 * ```tsx
 * import RoomDepositSettings from './RoomDepositSettings';
 *
 * function RoomCard({ room }) {
 *   return (
 *     <div className="room-card">
 *       <h3>{room.name}</h3>
 *       <p>Capacity: {room.capacity}</p>
 *
 *       // Option 1: Full settings panel
 *       <RoomDepositSettings
 *         roomId={room.id}
 *         roomName={room.name}
 *         initialConfig={room.depositConfig}
 *         onSave={(config) => console.log('Saved:', config)}
 *       />
 *
 *       // Option 2: Inline checkbox (compact)
 *       <RoomDepositSettings
 *         roomId={room.id}
 *         roomName={room.name}
 *         inline
 *       />
 *     </div>
 *   );
 * }
 * ```
 */
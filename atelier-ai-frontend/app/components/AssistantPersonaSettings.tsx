'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * AssistantPersonaSettings
 *
 * Lets managers choose who the AI represents in client messages.
 * This is style-only and does not affect workflow logic.
 */

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

interface AssistantPersonaSettingsProps {
  compact?: boolean;
}

export default function AssistantPersonaSettings({ compact = false }: AssistantPersonaSettingsProps) {
  const [representativeName, setRepresentativeName] = useState('');
  const [source, setSource] = useState<string>('default');
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await fetch(`${API_BASE}/config/assistant`);
        if (!response.ok) return;
        const data = await response.json();
        if (data && typeof data.representative_name === 'string') {
          setRepresentativeName(data.representative_name);
          setSource(data.source || 'database');
        }
      } catch (err) {
        console.warn('Could not load assistant persona config:', err);
      }
    };
    loadConfig();
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    setWarnings([]);
    setSuccessMessage(null);

    try {
      const response = await fetch(`${API_BASE}/config/assistant`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ representative_name: representativeName }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to save assistant persona');
      }

      const payload = await response.json();
      if (payload?.config?.representative_name) {
        setRepresentativeName(payload.config.representative_name);
      }
      if (Array.isArray(payload?.warnings)) {
        setWarnings(payload.warnings);
      }

      setIsEditing(false);
      setSource('database');
      setSuccessMessage('Assistant persona saved');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }, [representativeName]);

  return (
    <div className={`bg-white rounded-lg p-4 shadow-sm border border-gray-200 ${compact ? 'text-sm' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-gray-900">AI Representative</div>
          <div className="text-xs text-gray-500">Who the AI speaks as in client replies</div>
        </div>
        {!isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="px-2 py-1 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
          >
            Edit
          </button>
        )}
      </div>

      <div className="mt-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">Representative name</label>
        <input
          type="text"
          value={representativeName}
          onChange={(e) => setRepresentativeName(e.target.value)}
          disabled={!isEditing}
          placeholder="OpenEvent AI"
          className={`w-full rounded border px-3 py-2 text-sm ${
            isEditing ? 'border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-200' : 'border-gray-200 bg-gray-50'
          }`}
        />
        <div className="text-xs text-gray-400 mt-1">Style-only. Does not change workflow or logic.</div>
      </div>

      {warnings.length > 0 && (
        <div className="mt-2 text-xs text-amber-600">
          Some inputs were rejected for safety and reverted to default.
        </div>
      )}

      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {successMessage && <div className="mt-2 text-xs text-green-600">{successMessage}</div>}

      <div className="mt-3 flex items-center justify-between">
        <div className="text-xs text-gray-400">Source: {source}</div>
        {isEditing && (
          <div className="flex gap-2">
            <button
              onClick={() => setIsEditing(false)}
              className="px-3 py-1.5 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60"
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

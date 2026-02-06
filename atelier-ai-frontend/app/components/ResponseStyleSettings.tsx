'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

/**
 * ResponseStyleSettings
 *
 * Tone-only controls for LLM verbalization (safe, style-only).
 */

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

interface ResponseStyleSettingsProps {
  compact?: boolean;
}

const TONE_OPTIONS = [
  { value: 'formal', label: 'Formal' },
  { value: 'neutral', label: 'Neutral' },
  { value: 'friendly', label: 'Friendly' },
] as const;

const temperamentLabel = (value: number) => {
  if (value <= 20) return 'Reserved';
  if (value <= 40) return 'Calm';
  if (value <= 60) return 'Balanced';
  if (value <= 80) return 'Warm';
  return 'Enthusiastic';
};

export default function ResponseStyleSettings({ compact = false }: ResponseStyleSettingsProps) {
  const [tone, setTone] = useState<'formal' | 'neutral' | 'friendly'>('neutral');
  const [temperament, setTemperament] = useState(50);
  const [adjectives, setAdjectives] = useState('');
  const [source, setSource] = useState<string>('default');
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [rejectedAdjectives, setRejectedAdjectives] = useState<string[]>([]);

  const temperamentText = useMemo(() => temperamentLabel(temperament), [temperament]);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await fetch(`${API_BASE}/config/response-style`);
        if (!response.ok) return;
        const data = await response.json();
        if (data) {
          if (data.tone) setTone(data.tone);
          if (typeof data.temperament === 'number') setTemperament(data.temperament);
          if (typeof data.style_adjectives_raw === 'string') setAdjectives(data.style_adjectives_raw);
          setSource(data.source || 'database');
        }
      } catch (err) {
        console.warn('Could not load response style config:', err);
      }
    };
    loadConfig();
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    setRejectedAdjectives([]);
    setSuccessMessage(null);

    try {
      const response = await fetch(`${API_BASE}/config/response-style`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tone,
          temperament,
          style_adjectives: adjectives,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to save response style');
      }

      const payload = await response.json();
      if (payload?.config?.tone) setTone(payload.config.tone);
      if (typeof payload?.config?.temperament === 'number') setTemperament(payload.config.temperament);
      if (typeof payload?.config?.style_adjectives_raw === 'string') setAdjectives(payload.config.style_adjectives_raw);
      if (Array.isArray(payload?.rejected_adjectives)) setRejectedAdjectives(payload.rejected_adjectives);

      setIsEditing(false);
      setSource('database');
      setSuccessMessage('Response style saved');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }, [tone, temperament, adjectives]);

  return (
    <div className={`bg-white rounded-lg p-4 shadow-sm border border-gray-200 ${compact ? 'text-sm' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-gray-900">Response Style</div>
          <div className="text-xs text-gray-500">Tone-only controls for the AI verbalizer</div>
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

      <div className="mt-3 space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Tone</label>
          <div className="flex gap-2">
            {TONE_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => setTone(option.value)}
                disabled={!isEditing}
                className={`px-2.5 py-1.5 text-xs rounded border transition ${
                  tone === option.value
                    ? 'border-blue-500 bg-blue-50 text-blue-700'
                    : 'border-gray-300 text-gray-600'
                } ${!isEditing ? 'opacity-70 cursor-default' : 'hover:bg-gray-50'}`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Temperament</label>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={100}
              value={temperament}
              disabled={!isEditing}
              onChange={(e) => setTemperament(parseInt(e.target.value, 10))}
              className="w-full"
            />
            <div className="text-xs text-gray-600 w-20 text-right">{temperamentText}</div>
          </div>
          <div className="text-xs text-gray-400">{temperament}/100</div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Style adjectives</label>
          <input
            type="text"
            value={adjectives}
            onChange={(e) => setAdjectives(e.target.value)}
            disabled={!isEditing}
            placeholder="Concise, warm, professional"
            className={`w-full rounded border px-3 py-2 text-sm ${
              isEditing ? 'border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-200' : 'border-gray-200 bg-gray-50'
            }`}
          />
          <div className="text-xs text-gray-400 mt-1">Comma-separated adjectives only.</div>
        </div>
      </div>

      {rejectedAdjectives.length > 0 && (
        <div className="mt-2 text-xs text-amber-600">
          Rejected: {rejectedAdjectives.join(', ')}
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

export type OfferStatusDisplay =
  | '—'
  | 'In creation'
  | 'Waiting on HIL'
  | 'Confirmed by HIL'
  | string;

export type OfferChipTone = 'info' | 'warn' | 'success' | 'muted';

interface OfferStatusChip {
  tone: OfferChipTone;
  label: string;
}

const OFFER_TONE_MAP: Record<string, OfferChipTone> = {
  '—': 'muted',
  'in creation': 'info',
  'waiting on hil': 'warn',
  'confirmed by hil': 'success',
};

export function resolveOfferStatusChip(status: OfferStatusDisplay | null | undefined): OfferStatusChip {
  const label = typeof status === 'string' && status.trim().length ? status.trim() : '—';
  const tone = OFFER_TONE_MAP[label.toLowerCase()] ?? 'info';
  return { tone, label };
}

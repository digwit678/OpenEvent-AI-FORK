export const SUBLOOP_COLORS = {
  general_q_a: '#2E77D0',
  shortcut: '#7A3EE6',
} as const;

export type SubloopKey = keyof typeof SUBLOOP_COLORS;

export const SUBLOOP_LABELS: Record<SubloopKey, string> = {
  general_q_a: 'Availability overview',
  shortcut: 'Shortcut',
};

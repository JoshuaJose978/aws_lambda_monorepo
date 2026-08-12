export function messageFor(reason: unknown): string {
  return reason instanceof Error ? reason.message : 'An unexpected error occurred';
}

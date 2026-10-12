// IP-based HTTP deployments are not secure contexts. getRandomValues still
// works there, unlike randomUUID and the asynchronous clipboard API.
import {translate} from '../i18n';
export function messageId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back when clipboard access is blocked by browser permissions.
    }
  }
  const focused = document.activeElement as HTMLElement | null;
  const input = document.createElement('textarea');
  input.value = text;
  input.style.cssText = 'position:fixed;left:-9999px;top:0;';
  document.body.appendChild(input);
  try {
    input.select();
    if (!document.execCommand('copy')) throw new Error(translate('复制失败，请手动选择文本复制'));
  } finally {
    input.remove();
    focused?.focus();
  }
}

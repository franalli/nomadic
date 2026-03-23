/**
 * Advisory multi-tab guard using BroadcastChannel.
 * Backend SSE slot limiter (MAX_SSE_PER_SESSION=2) is the hard enforcement.
 * This provides UX feedback before the user hits server-side limits.
 */

const CHANNEL_NAME = 'nomadic-tab-guard';

let channel: BroadcastChannel | null = null;
let tabId = '';
let isActive = true;

export function initTabGuard(): void {
  if (typeof BroadcastChannel === 'undefined') return;
  tabId = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.addEventListener('message', (e: MessageEvent) => {
    if (e.data?.type === 'claim' && e.data.tabId !== tabId) {
      isActive = false;
    }
  });
}

export function claimActiveTab(): boolean {
  if (!channel) return true; // graceful degradation
  channel.postMessage({ type: 'claim', tabId });
  isActive = true;
  return true;
}

export function isActiveTab(): boolean {
  return isActive;
}

export function destroyTabGuard(): void {
  channel?.close();
  channel = null;
}

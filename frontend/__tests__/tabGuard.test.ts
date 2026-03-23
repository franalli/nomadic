import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('tabGuard', () => {
  let mockPostMessage: ReturnType<typeof vi.fn>;
  let mockClose: ReturnType<typeof vi.fn>;
  let mockAddEventListener: ReturnType<typeof vi.fn>;
  let messageHandlers: ((e: MessageEvent) => void)[];

  let tabGuard: typeof import('@/lib/tabGuard');

  beforeEach(async () => {
    vi.resetModules();

    messageHandlers = [];
    mockPostMessage = vi.fn();
    mockClose = vi.fn();
    mockAddEventListener = vi.fn((event: string, handler: unknown) => {
      if (event === 'message') messageHandlers.push(handler as (e: MessageEvent) => void);
    });

    // Must use function() (not arrow) so it can be called with `new`
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.BroadcastChannel = vi.fn(function (this: any) {
      this.postMessage = mockPostMessage;
      this.close = mockClose;
      this.addEventListener = mockAddEventListener;
    }) as unknown as typeof BroadcastChannel;

    tabGuard = await import('@/lib/tabGuard');
  });

  afterEach(() => {
    tabGuard.destroyTabGuard();
    // @ts-expect-error -- cleanup mock from globalThis
    delete globalThis.BroadcastChannel;
  });

  it('initTabGuard creates a BroadcastChannel with the correct name', () => {
    tabGuard.initTabGuard();

    expect(globalThis.BroadcastChannel).toHaveBeenCalledTimes(1);
    expect(globalThis.BroadcastChannel).toHaveBeenCalledWith('nomadic-tab-guard');
  });

  it('isActiveTab returns true initially before any claims', () => {
    expect(tabGuard.isActiveTab()).toBe(true);
  });

  it('claimActiveTab posts a message with type claim and tabId', () => {
    tabGuard.initTabGuard();
    tabGuard.claimActiveTab();

    expect(mockPostMessage).toHaveBeenCalledTimes(1);
    const posted = mockPostMessage.mock.calls[0][0];
    expect(posted.type).toBe('claim');
    expect(typeof posted.tabId).toBe('string');
    expect(posted.tabId.length).toBeGreaterThan(0);
  });

  it('claimActiveTab sets isActiveTab to true', () => {
    tabGuard.initTabGuard();
    tabGuard.claimActiveTab();

    expect(tabGuard.isActiveTab()).toBe(true);
  });

  it('receiving a claim from another tab deactivates this tab', () => {
    tabGuard.initTabGuard();

    expect(messageHandlers).toHaveLength(1);

    // Simulate a claim arriving from a different tab
    const foreignEvent = { data: { type: 'claim', tabId: 'foreign-tab-xyz' } } as MessageEvent;
    messageHandlers[0](foreignEvent);

    expect(tabGuard.isActiveTab()).toBe(false);
  });

  it('claimActiveTab re-activates after being deactivated by another tab', () => {
    tabGuard.initTabGuard();

    // Deactivate via foreign claim
    const foreignEvent = { data: { type: 'claim', tabId: 'foreign-tab-xyz' } } as MessageEvent;
    messageHandlers[0](foreignEvent);
    expect(tabGuard.isActiveTab()).toBe(false);

    // Re-claim
    tabGuard.claimActiveTab();
    expect(tabGuard.isActiveTab()).toBe(true);
  });

  it('destroyTabGuard closes the channel', () => {
    tabGuard.initTabGuard();
    tabGuard.destroyTabGuard();

    expect(mockClose).toHaveBeenCalledTimes(1);
  });

  it('claimActiveTab returns true when no channel exists (graceful degradation)', async () => {
    // Re-import with no BroadcastChannel at all — need a fresh module
    vi.resetModules();
    // @ts-expect-error -- remove mock so BroadcastChannel is undefined
    delete globalThis.BroadcastChannel;

    const fresh = await import('@/lib/tabGuard');
    // initTabGuard not called, channel is null
    const result = fresh.claimActiveTab();

    expect(result).toBe(true);
  });

  it('initTabGuard is a no-op when BroadcastChannel is undefined', async () => {
    vi.resetModules();
    // @ts-expect-error -- remove mock so typeof BroadcastChannel === "undefined"
    delete globalThis.BroadcastChannel;

    const fresh = await import('@/lib/tabGuard');
    fresh.initTabGuard();

    // isActiveTab still returns the default true — nothing broke
    expect(fresh.isActiveTab()).toBe(true);
  });

  it('a claim with the same tabId does NOT deactivate this tab', () => {
    tabGuard.initTabGuard();
    tabGuard.claimActiveTab();

    // Extract the tabId that was posted
    const ownTabId = mockPostMessage.mock.calls[0][0].tabId;

    // Simulate receiving our own claim back (same tabId)
    const selfEvent = { data: { type: 'claim', tabId: ownTabId } } as MessageEvent;
    messageHandlers[0](selfEvent);

    expect(tabGuard.isActiveTab()).toBe(true);
  });
});

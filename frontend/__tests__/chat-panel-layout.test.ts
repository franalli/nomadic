import { describe, expect, it } from 'vitest';

import {
  shouldShowBootstrapHero,
  shouldUseLandingChatLayout,
} from '@/components/chat/chatPanelLayout';

describe('chatPanelLayout', () => {
  it('uses landing layout for idle desktop bootstrap state', () => {
    expect(
      shouldUseLandingChatLayout({
        isDesktop: true,
        planViewState: null,
      })
    ).toBe(true);
  });

  it('does not use landing layout during active first-load framing', () => {
    expect(
      shouldUseLandingChatLayout({
        isDesktop: true,
        planViewState: null,
        isFraming: true,
        isGenerating: true,
      })
    ).toBe(false);
  });

  it('does not show the bootstrap hero while generation is active', () => {
    expect(
      shouldShowBootstrapHero({
        isDesktop: true,
        planViewState: null,
        isFraming: true,
        isGenerating: true,
        isSetupHeaderCollapsed: false,
      })
    ).toBe(false);
  });
});

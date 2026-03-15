import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatScrolling } from '@/hooks/useChatScrolling';

function buildScrollContainer(initialScrollHeight = 400, initialClientHeight = 100) {
  const container = document.createElement('div');
  let scrollHeight = initialScrollHeight;
  let clientHeight = initialClientHeight;
  let scrollTop = 0;

  Object.defineProperty(container, 'scrollHeight', {
    configurable: true,
    get: () => scrollHeight,
  });
  Object.defineProperty(container, 'clientHeight', {
    configurable: true,
    get: () => clientHeight,
  });
  Object.defineProperty(container, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });

  return {
    container,
    getScrollTop: () => scrollTop,
    setScrollHeight: (value: number) => {
      scrollHeight = value;
    },
    setClientHeight: (value: number) => {
      clientHeight = value;
    },
    setScrollTop: (value: number) => {
      scrollTop = value;
    },
  };
}

function buildScrollableAncestor(initialScrollHeight = 900, initialClientHeight = 300) {
  const container = document.createElement('div');
  container.style.overflowY = 'auto';
  let scrollHeight = initialScrollHeight;
  let clientHeight = initialClientHeight;
  let scrollTop = 0;

  Object.defineProperty(container, 'scrollHeight', {
    configurable: true,
    get: () => scrollHeight,
  });
  Object.defineProperty(container, 'clientHeight', {
    configurable: true,
    get: () => clientHeight,
  });
  Object.defineProperty(container, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });

  container.scrollTo = vi.fn(({ top }: { top?: number }) => {
    scrollTop = top ?? 0;
  }) as typeof container.scrollTo;

  return {
    container,
    getScrollTop: () => scrollTop,
    setScrollHeight: (value: number) => {
      scrollHeight = value;
    },
    setScrollTop: (value: number) => {
      scrollTop = value;
    },
  };
}

describe('useChatScrolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', ((callback: FrameRequestCallback) =>
      window.setTimeout(
        () => callback(performance.now()),
        16
      )) as typeof requestAnimationFrame);
    vi.stubGlobal('cancelAnimationFrame', ((handle: number) =>
      window.clearTimeout(handle)) as typeof cancelAnimationFrame);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('reasserts the real bottom after a forced scroll when content keeps growing', () => {
    const panel = document.createElement('div');
    const onSetupHeaderCollapse = vi.fn();
    const scrollState = buildScrollContainer();

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse,
      })
    );

    act(() => {
      result.current.scrollContainerRef.current = scrollState.container;
      result.current.scrollToBottom(true);
      vi.advanceTimersByTime(16);
    });

    expect(scrollState.getScrollTop()).toBe(300);

    act(() => {
      scrollState.setScrollHeight(640);
      vi.advanceTimersByTime(80);
    });

    expect(scrollState.getScrollTop()).toBe(540);

    act(() => {
      scrollState.setScrollHeight(760);
      vi.advanceTimersByTime(240);
    });

    expect(scrollState.getScrollTop()).toBe(660);
  });

  it('keeps settling when the chat viewport shifts well after the initial snap', () => {
    const panel = document.createElement('div');
    const onSetupHeaderCollapse = vi.fn();
    const scrollState = buildScrollContainer();

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse,
      })
    );

    act(() => {
      result.current.scrollContainerRef.current = scrollState.container;
      result.current.scrollToBottom(true);
      vi.advanceTimersByTime(16);
    });

    expect(scrollState.getScrollTop()).toBe(300);

    act(() => {
      vi.advanceTimersByTime(480);
      scrollState.setClientHeight(40);
      vi.advanceTimersByTime(80);
    });

    expect(scrollState.getScrollTop()).toBe(360);
  });

  it('cancels forced settling when the user nudges upward near the bottom immediately', () => {
    const panel = document.createElement('div');
    const onSetupHeaderCollapse = vi.fn();
    const scrollState = buildScrollContainer();

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse,
      })
    );

    act(() => {
      result.current.scrollContainerRef.current = scrollState.container;
      result.current.scrollToBottom(true);
      vi.advanceTimersByTime(16);
    });

    expect(scrollState.getScrollTop()).toBe(300);

    act(() => {
      scrollState.setScrollTop(280);
      result.current.handleScroll();
      scrollState.setScrollHeight(440);
      vi.advanceTimersByTime(500);
    });

    expect(scrollState.getScrollTop()).toBe(280);
    expect(result.current.isUserScrolledUp()).toBe(true);
  });

  it('cancels pending forced settle work when the user scrolls up', () => {
    const panel = document.createElement('div');
    const onSetupHeaderCollapse = vi.fn();
    const scrollState = buildScrollContainer();

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse,
      })
    );

    act(() => {
      result.current.scrollContainerRef.current = scrollState.container;
      result.current.scrollToBottom(true);
      vi.advanceTimersByTime(16);
    });

    expect(scrollState.getScrollTop()).toBe(300);

    act(() => {
      vi.advanceTimersByTime(60);
      scrollState.setScrollTop(120);
      result.current.handleScroll();
      scrollState.setScrollHeight(760);
      vi.advanceTimersByTime(500);
    });

    expect(scrollState.getScrollTop()).toBe(120);
    expect(result.current.isUserScrolledUp()).toBe(true);
  });

  it('scrolls the outer planner rail to its absolute bottom', () => {
    const panel = document.createElement('div');
    const rail = buildScrollableAncestor();
    rail.container.appendChild(panel);

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse: vi.fn(),
      })
    );

    act(() => {
      result.current.scrollPanelIntoView();
      vi.advanceTimersByTime(16);
    });

    expect(rail.getScrollTop()).toBe(600);
    expect(rail.container.scrollTo).toHaveBeenCalledWith({
      top: 600,
      behavior: 'smooth',
    });
  });

  it('re-settles the outer planner rail when its height grows after the first frame', () => {
    const panel = document.createElement('div');
    const rail = buildScrollableAncestor();
    rail.container.appendChild(panel);

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse: vi.fn(),
      })
    );

    act(() => {
      result.current.scrollPanelIntoView();
      vi.advanceTimersByTime(16);
    });

    expect(rail.getScrollTop()).toBe(600);

    act(() => {
      rail.setScrollHeight(1040);
      vi.advanceTimersByTime(80);
    });

    expect(rail.getScrollTop()).toBe(740);
    expect(rail.container.scrollTo).toHaveBeenLastCalledWith({
      top: 740,
      behavior: 'auto',
    });
  });

  it('keeps the mobile fallback path and does not snap the outer rail', () => {
    const panel = document.createElement('div');
    const rail = buildScrollableAncestor();
    const scrollIntoView = vi.fn();
    panel.scrollIntoView = scrollIntoView;
    rail.container.appendChild(panel);

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: false,
        onSetupHeaderCollapse: vi.fn(),
      })
    );

    act(() => {
      result.current.scrollPanelIntoView();
      vi.advanceTimersByTime(16);
    });

    expect(rail.getScrollTop()).toBe(0);
    expect(rail.container.scrollTo).not.toHaveBeenCalled();
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'end',
    });
  });

  it('cancels planner-rail settling when the user scrolls that rail upward', () => {
    const panel = document.createElement('div');
    const rail = buildScrollableAncestor();
    rail.container.appendChild(panel);

    const { result } = renderHook(() =>
      useChatScrolling({
        panelRef: { current: panel },
        isDesktop: true,
        onSetupHeaderCollapse: vi.fn(),
      })
    );

    act(() => {
      result.current.scrollPanelIntoView();
      vi.advanceTimersByTime(16);
    });

    expect(rail.getScrollTop()).toBe(600);

    act(() => {
      rail.setScrollTop(540);
      rail.container.dispatchEvent(new Event('scroll'));
      rail.setScrollHeight(1040);
      vi.advanceTimersByTime(500);
    });

    expect(rail.getScrollTop()).toBe(540);
  });
});

import { act, fireEvent, render, screen, within } from '@testing-library/react';
import type { ImgHTMLAttributes, ReactNode } from 'react';
import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatPanelHandle, ChatPanelProps } from '@/components/chat/ChatPanel';
import type { Tile } from '@/types/tile';

const sharedMocks = vi.hoisted(() => ({
  errorBoundary: vi.fn(({ label, children }: { label?: string; children: ReactNode }) => (
    <div data-testid="error-boundary" data-label={label ?? ''}>
      {children}
    </div>
  )),
}));

const landingMocks = vi.hoisted(() => ({
  floatingBuildButton: vi.fn((_props: unknown) => <div data-testid="floating-build-button" />),
  landingSheets: vi.fn((_props: unknown) => <div data-testid="landing-sheets" />),
  splitLayoutView: vi.fn((_props: unknown) => <div data-testid="split-layout-view" />),
  useController: vi.fn(),
}));

const chatPanelMocks = vi.hoisted(() => ({
  chatBootstrapHero: vi.fn((_props: unknown) => <div data-testid="chat-bootstrap-hero" />),
  chatInputHandler: vi.fn((_props: unknown) => <div data-testid="chat-input-handler" />),
  chatMessageList: vi.fn(
    ({
      isLanding,
      scrollHeaderContent,
    }: {
      isLanding?: boolean;
      scrollHeaderContent?: ReactNode;
    }) => (
      <div data-testid="chat-message-list" data-is-landing={String(Boolean(isLanding))}>
        {scrollHeaderContent ? (
          <div data-testid="chat-message-list-header">{scrollHeaderContent}</div>
        ) : null}
      </div>
    )
  ),
  chatModuleSheets: vi.fn((_props: unknown) => <div data-testid="chat-module-sheets" />),
  chatStatusHeader: vi.fn((_props: unknown) => <div data-testid="chat-status-header" />),
  chatSuggestionBar: vi.fn((_props: unknown) => <div data-testid="chat-suggestion-bar" />),
  isBootstrap: vi.fn((_planViewState?: unknown) => false),
  smartLoader: vi.fn(({ status }: { status: { label: string } }) => (
    <div data-testid="smart-loader">{status.label}</div>
  )),
  useController: vi.fn(),
}));

const suggestionCardMocks = vi.hoisted(() => ({
  trackDeeplinkClick: vi.fn((_tileId?: unknown) => undefined),
}));

vi.mock('next/image', () => ({
  default: ({
    alt,
    fill: _fill,
    priority: _priority,
    ...props
  }: ImgHTMLAttributes<HTMLImageElement> & { fill?: boolean; priority?: boolean }) => (
    <img alt={alt} {...props} />
  ),
}));

vi.mock('@/components/ui/ErrorBoundary', () => ({
  ErrorBoundary: (props: unknown) =>
    sharedMocks.errorBoundary(props as { label?: string; children: ReactNode }),
}));

vi.mock('@/components/layout/FloatingBuildButton', () => ({
  FloatingBuildButton: (props: unknown) => landingMocks.floatingBuildButton(props),
}));

vi.mock('@/components/layout/hooks/useNomadicLandingController', () => ({
  useNomadicLandingController: landingMocks.useController,
}));

vi.mock('@/components/layout/LandingSheets', () => ({
  LandingSheets: (props: unknown) => landingMocks.landingSheets(props),
}));

vi.mock('@/components/layout/SplitLayoutView', () => ({
  SplitLayoutView: (props: unknown) => landingMocks.splitLayoutView(props),
}));

vi.mock('@/components/plan/planStateHelpers', () => ({
  isBootstrap: chatPanelMocks.isBootstrap,
}));

vi.mock('@/components/chat/ChatBootstrapHero', () => ({
  ChatBootstrapHero: (props: unknown) => chatPanelMocks.chatBootstrapHero(props),
}));

vi.mock('@/components/chat/ChatInputHandler', () => ({
  ChatInputHandler: (props: unknown) => chatPanelMocks.chatInputHandler(props),
}));

vi.mock('@/components/chat/ChatMessageList', () => ({
  ChatMessageList: (props: unknown) =>
    chatPanelMocks.chatMessageList(props as { isLanding?: boolean; scrollHeaderContent?: ReactNode }),
}));

vi.mock('@/components/chat/ChatModuleSheets', () => ({
  ChatModuleSheets: (props: unknown) => chatPanelMocks.chatModuleSheets(props),
}));

vi.mock('@/components/chat/ChatStatusHeader', () => ({
  ChatStatusHeader: (props: unknown) => chatPanelMocks.chatStatusHeader(props),
}));

vi.mock('@/components/chat/ChatSuggestionBar', () => ({
  ChatSuggestionBar: (props: unknown) => chatPanelMocks.chatSuggestionBar(props),
}));

vi.mock('@/components/chat/SmartLoader', () => ({
  SmartLoader: (props: unknown) =>
    chatPanelMocks.smartLoader(props as { status: { label: string } }),
}));

vi.mock('@/components/chat/useChatPanelController', () => ({
  useChatPanelController: chatPanelMocks.useController,
}));

vi.mock('@/lib/api-streaming', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-streaming')>('@/lib/api-streaming');
  return {
    ...actual,
    trackDeeplinkClick: suggestionCardMocks.trackDeeplinkClick,
  };
});

import { ChatPanel } from '@/components/chat/ChatPanel';
import NomadicLandingWithProvider, { NomadicLanding } from '@/components/layout/NomadicLanding';
import { SuggestionCard } from '@/components/plan/tiles/SuggestionCard';
import { TileCardContent } from '@/components/tiles/TileCardContent';
import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';

function buildTile(overrides: Partial<Tile> = {}): Tile {
  return {
    id: 'tile_1',
    type: 'hotel',
    title: 'Canal House',
    subtitle: 'Amsterdam Center',
    currency: 'USD',
    deeplink_url: 'https://maps.google.com/?q=canal-house',
    image_url: 'https://images.unsplash.com/photo-canal-house?w=600&h=400&fit=crop',
    price_estimate: 240,
    price_basis: 'per_night',
    location_label: 'Amsterdam Center',
    rating: 4.8,
    is_refundable: true,
    meta: {
      images: [
        'https://images.unsplash.com/photo-canal-house?w=600&h=400&fit=crop',
        'https://images.unsplash.com/photo-canal-house-2?w=600&h=400&fit=crop',
      ],
      amenities: ['Breakfast included', 'Canal view'],
      check_in: '15:00',
      check_out: '11:00',
      cancellation_deadline: 'April 1',
      review_count: 321,
      reasoning: 'Close to the canals and walkable nightlife.',
      is_ai_pick: true,
      nights: 3,
    },
    ...overrides,
  };
}

function buildChatProps(overrides: Partial<ChatPanelProps> = {}): ChatPanelProps {
  return {
    selectedBranchId: 'branch_1',
    onPlanResult: vi.fn(),
    readyToGenerate: true,
    hasBranches: true,
    isGenerating: false,
    planState: 'STABLE',
    destination: 'Rome',
    origin: 'Amsterdam',
    dateRange: 'Apr 3 - Apr 7',
    budget: '$2,000',
    hasDestination: true,
    hasDates: true,
    bookingTypes: {
      hotels: 'suggested',
      flights: 'suggested',
      ground_transport: 'off',
      activities: 'suggested',
    },
    flightSettings: {
      round_trip: true,
      cabin_class: 'economy',
      direct_only: false,
    },
    hotelSettings: {
      min_stars: 0,
      amenities: [],
    },
    activitySettings: {
      categories: [],
      skill_level: null,
    },
    onUpdateBookingTypes: vi.fn(),
    onUpdateFlightSettings: vi.fn(),
    onUpdateHotelSettings: vi.fn(),
    onUpdateActivitySettings: vi.fn(),
    onOpenSheet: vi.fn(),
    onConfirmReset: vi.fn(),
    planViewState: 'P0_MINIMAL',
    ...overrides,
  };
}

function buildChatControllerState(overrides: Record<string, unknown> = {}) {
  return {
    activeStatus: null,
    scrollContainerRef: { current: null },
    bottomSentinelRef: { current: null },
    chatSend: {
      addAssistantMessage: vi.fn(),
      handleStopStreaming: vi.fn(),
      handleSubmit: vi.fn(),
      hasReceivedFirstToken: false,
      input: '',
      isLoading: false,
      lastUserMessage: 'Help me plan Rome',
      nodeStatus: null,
      sendMessageCore: vi.fn().mockResolvedValue(undefined),
      setInput: vi.fn(),
      streamedMessage: null,
      streamingMessageId: null,
      suggestionChips: [],
      suggestedResponseMeta: [],
      suggestedResponses: [],
    },
    effectiveSuggestions: ['Set my budget'],
    handleScroll: vi.fn(),
    inputRef: { current: null },
    isDesktop: true,
    isInputDisabledByPlanState: false,
    isLoadingHistory: false,
    isRegenerating: false,
    isSetupHeaderCollapsed: false,
    openModuleSheet: null,
    panelHeightClass: 'h-full',
    panelRef: { current: null },
    setOpenModuleSheet: vi.fn(),
    toast: vi.fn(),
    visibleMessages: [{ id: 'user_1', role: 'user', content: 'Help me plan Rome' }],
    ...overrides,
  };
}

describe('Split render surfaces', () => {
  describe('NomadicLanding', () => {
    beforeEach(() => {
      sharedMocks.errorBoundary.mockClear();
      landingMocks.useController.mockReset();
      landingMocks.floatingBuildButton.mockClear();
      landingMocks.landingSheets.mockClear();
      landingMocks.splitLayoutView.mockClear();

      landingMocks.useController.mockReturnValue({
        splitLayoutProps: {
          plannerContent: <div>Planner surface</div>,
          planViewContent: <div>Plan surface</div>,
          planTabEnabled: true,
        },
        landingSheetsProps: {
          activeSheet: 'dates',
          closeSheet: vi.fn(),
        },
        floatingBuildButtonProps: {
          visible: true,
          onClick: vi.fn(),
          hasEverHadPlan: true,
        },
      });
    });

    it('renders the controller-driven landing shell and app boundary', () => {
      const { container } = render(<NomadicLanding />);

      expect(landingMocks.useController).toHaveBeenCalledTimes(1);
      expect(landingMocks.splitLayoutView.mock.calls[0]?.[0]).toMatchObject({
        plannerContent: expect.any(Object),
        planViewContent: expect.any(Object),
        planTabEnabled: true,
      });
      expect(landingMocks.floatingBuildButton.mock.calls[0]?.[0]).toMatchObject({
        visible: true,
        hasEverHadPlan: true,
      });
      expect(landingMocks.landingSheets.mock.calls[0]?.[0]).toMatchObject({
        activeSheet: 'dates',
      });
      expect(container.querySelector('.appTopo')).not.toBeNull();
      expect(screen.getByTestId('split-layout-view')).toBeInTheDocument();
      expect(screen.getByTestId('floating-build-button')).toBeInTheDocument();
      expect(screen.getByTestId('landing-sheets')).toBeInTheDocument();

      render(<NomadicLandingWithProvider />);

      expect(sharedMocks.errorBoundary.mock.calls.at(-1)?.[0]).toMatchObject({
        label: 'App',
      });
      expect(screen.getByTestId('error-boundary')).toHaveAttribute('data-label', 'App');
    });
  });

  describe('ChatPanel', () => {
    beforeEach(() => {
      sharedMocks.errorBoundary.mockClear();
      chatPanelMocks.chatBootstrapHero.mockClear();
      chatPanelMocks.chatInputHandler.mockClear();
      chatPanelMocks.chatMessageList.mockClear();
      chatPanelMocks.chatModuleSheets.mockClear();
      chatPanelMocks.chatStatusHeader.mockClear();
      chatPanelMocks.chatSuggestionBar.mockClear();
      chatPanelMocks.isBootstrap.mockReset();
      chatPanelMocks.smartLoader.mockClear();
      chatPanelMocks.useController.mockReset();

      chatPanelMocks.isBootstrap.mockReturnValue(true);
      chatPanelMocks.useController.mockReturnValue(buildChatControllerState());
    });

    it('renders desktop composition and exposes the imperative handle', async () => {
      const props = buildChatProps();
      const ref = createRef<ChatPanelHandle>();

      render(<ChatPanel {...props} ref={ref} />);

      expect(chatPanelMocks.chatStatusHeader).toHaveBeenCalledTimes(1);
      expect(chatPanelMocks.chatMessageList.mock.calls[0]?.[0]).toMatchObject({
        isDesktop: true,
        isLanding: true,
        planViewState: 'P0_MINIMAL',
      });
      expect(screen.getByTestId('chat-message-list-header')).toBeInTheDocument();
      expect(screen.getByTestId('chat-bootstrap-hero')).toBeInTheDocument();
      expect(screen.getByTestId('chat-input-handler')).toBeInTheDocument();
      expect(screen.getByTestId('chat-suggestion-bar')).toBeInTheDocument();
      expect(screen.getByTestId('chat-module-sheets')).toBeInTheDocument();

      await act(async () => {
        await ref.current?.sendMessage('Build the trip');
      });
      act(() => {
        ref.current?.addAssistantMessage('Here is a draft');
        ref.current?.stopStreaming();
      });

      const chatSend = chatPanelMocks.useController.mock.results[0]?.value.chatSend;
      expect(chatSend.sendMessageCore).toHaveBeenCalledWith('Build the trip');
      expect(chatSend.addAssistantMessage).toHaveBeenCalledWith('Here is a draft');
      expect(chatSend.handleStopStreaming).toHaveBeenCalledTimes(1);
    });

    it('switches loader precedence and mobile-only rendering correctly', () => {
      chatPanelMocks.useController.mockReturnValue(
        buildChatControllerState({
          activeStatus: { label: 'SEARCHING INVENTORY', icon_key: 'plane' },
          isRegenerating: true,
          chatSend: {
            ...buildChatControllerState().chatSend,
            isLoading: true,
          },
        })
      );

      const desktopView = render(<ChatPanel {...buildChatProps()} />);

      expect(screen.getByTestId('smart-loader')).toHaveTextContent('REBUILDING ITINERARY');
      expect(screen.queryByText('SEARCHING INVENTORY')).not.toBeInTheDocument();

      desktopView.unmount();

      chatPanelMocks.isBootstrap.mockReturnValue(false);
      chatPanelMocks.useController.mockReturnValue(
        buildChatControllerState({
          isDesktop: false,
          visibleMessages: [],
        })
      );

      render(<ChatPanel {...buildChatProps({ planViewState: 'P3_FINALIZED' })} />);

      expect(screen.queryByTestId('chat-status-header')).not.toBeInTheDocument();
      expect(screen.queryByTestId('chat-input-handler')).not.toBeInTheDocument();
      expect(chatPanelMocks.chatMessageList.mock.calls.at(-1)?.[0]).toMatchObject({
        isDesktop: false,
        isLanding: false,
        scrollHeaderContent: undefined,
      });
    });

    it('tightens the desktop panel height while the first user prompt is still loading', () => {
      chatPanelMocks.useController.mockReturnValue(
        buildChatControllerState({
          panelHeightClass: 'min-h-[300px]',
          chatSend: {
            ...buildChatControllerState().chatSend,
            isLoading: true,
          },
          visibleMessages: [{ id: 'user_1', role: 'user', content: 'Bali diving April 1-7' }],
        })
      );

      const { rerender } = render(<ChatPanel {...buildChatProps()} />);
      const panelRoot = screen.getByTestId('error-boundary').firstElementChild;

      expect(panelRoot).toHaveClass('min-h-[220px]');
      expect(panelRoot).not.toHaveClass('min-h-[300px]');

      chatPanelMocks.useController.mockReturnValue(
        buildChatControllerState({
          panelHeightClass: 'min-h-[300px]',
          chatSend: {
            ...buildChatControllerState().chatSend,
            isLoading: true,
          },
          visibleMessages: [
            { id: 'user_1', role: 'user', content: 'Bali diving April 1-7' },
            { id: 'assistant_1', role: 'assistant', content: 'Working on it now.' },
          ],
        })
      );

      rerender(<ChatPanel {...buildChatProps()} />);

      expect(panelRoot).toHaveClass('min-h-[300px]');
      expect(panelRoot).not.toHaveClass('min-h-[220px]');
    });
  });

  describe('TileCardContent', () => {
    it('renders hotel and activity card states with the shared actions surface', () => {
      const onViewDetailsClick = vi.fn();

      const { rerender } = render(
        <TileCardContent
          tile={buildTile({
            type: 'stay',
            rating: 4.4,
            price_estimate: 249.4,
          })}
          isHotel={true}
          activityMeta={null}
          amenityIcons={[
            { icon: '📶', label: 'Wifi' },
            { icon: '🏊', label: 'Pool' },
          ]}
          relevanceBadges={['Free cancellation', 'Breakfast included']}
          features={['Canal view', 'Spa']}
          onViewDetailsClick={onViewDetailsClick}
        />
      );

      expect(screen.getByText('Canal House')).toBeInTheDocument();
      expect(screen.getByText('★★★★')).toBeInTheDocument();
      expect(screen.getByText('Amsterdam Center')).toBeInTheDocument();
      expect(screen.getByText('Free cancellation')).toBeInTheDocument();
      expect(screen.getByText('Breakfast included')).toBeInTheDocument();
      expect(screen.getByText('Canal view')).toBeInTheDocument();
      expect(screen.getByText('Spa')).toBeInTheDocument();
      expect(screen.getByText('From')).toBeInTheDocument();
      expect(screen.getByText('249')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Map' })).toHaveAttribute(
        'href',
        'https://maps.google.com/?q=canal-house'
      );

      fireEvent.click(screen.getByRole('button', { name: 'Details' }));
      expect(onViewDetailsClick).toHaveBeenCalledTimes(1);

      rerender(
        <TileCardContent
          tile={buildTile({
            id: 'activity_1',
            type: 'activity',
            title: 'Reef Safari',
            rating: 4.7,
            currency: 'EUR',
            deeplink_url: 'https://www.viator.com/tours/bali/reef-safari',
            total_inclusive: 180,
            tax_and_service_fee: 14,
            property_fee: 6,
          })}
          isHotel={false}
          activityMeta={{
            category: 'diving',
            durationHours: 4,
            timeOfDay: 'morning',
            description: 'Boat dive with guide',
          }}
          amenityIcons={[]}
          relevanceBadges={[]}
          features={['Gear included']}
          onViewDetailsClick={vi.fn()}
        />
      );

      expect(screen.getByText('Reef Safari')).toBeInTheDocument();
      expect(screen.getByText('4.7')).toBeInTheDocument();
      expect(screen.getByText('diving')).toBeInTheDocument();
      expect(screen.getByText('4h')).toBeInTheDocument();
      expect(screen.getByText('Morning')).toBeInTheDocument();
      expect(screen.getByText('Boat dive with guide')).toBeInTheDocument();
      expect(screen.getByText('Total from')).toBeInTheDocument();
      expect(screen.getByText('180')).toBeInTheDocument();
      expect(screen.getByText('Incl. 20 EUR taxes & fees')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Book' })).toHaveAttribute(
        'href',
        'https://www.viator.com/tours/bali/reef-safari'
      );
    });
  });

  describe('TileDetailsModal', () => {
    const windowOpen = vi.fn();
    let windowOpenSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      document.body.innerHTML = '';
      document.body.style.overflow = '';
      windowOpen.mockReset();
      windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(windowOpen as typeof window.open);
    });

    afterEach(() => {
      windowOpenSpy.mockRestore();
    });

    it('renders in a portal, computes detail props, and routes footer actions', () => {
      const tile = buildTile({
        deeplink_url: 'https://google.com/travel/hotels/canal-house',
      });
      const onSaveClick = vi.fn();
      const onClose = vi.fn();
      const onOpenSheet = vi.fn();
      const { unmount } = render(
        <TileDetailsModal
          tile={tile}
          isOpen={true}
          isSaved={true}
          isBookingUnlocked={false}
          onClose={onClose}
          onSaveClick={onSaveClick}
          onOpenSheet={onOpenSheet}
        />
      );

      expect(screen.getByText('Canal House')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Previous image' })).toBeInTheDocument();
      expect(document.body.style.overflow).toBe('hidden');
      const keyFactsSection = screen.getByText('Key facts').closest('div');
      expect(keyFactsSection).not.toBeNull();
      const keyFacts = within(keyFactsSection as HTMLElement);
      expect(keyFacts.getByText(/Check-in:\s*15:00/, { selector: 'li' })).toBeInTheDocument();
      expect(keyFacts.getByText(/Check-out:\s*11:00/, { selector: 'li' })).toBeInTheDocument();
      expect(keyFacts.getByText(/Free cancellation until April 1/, { selector: 'li' })).toBeInTheDocument();
      expect(screen.getByText('Breakfast included')).toBeInTheDocument();
      expect(screen.getByText('Canal view')).toBeInTheDocument();
      expect(screen.getByText('$240 /night')).toBeInTheDocument();
      expect(screen.getByText('$720 total (3 nights)')).toBeInTheDocument();
      expect(screen.getByText('Why this suggestion?')).toBeInTheDocument();
      expect(screen.getByText('AI Pick')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /saved to shortlist/i }));
      fireEvent.click(screen.getByRole('button', { name: /view on google travel/i }));
      fireEvent.click(screen.getByRole('button', { name: /set trip dates to unlock booking/i }));
      fireEvent.click(screen.getByRole('button', { name: /close/i }));

      expect(onSaveClick).toHaveBeenCalledWith(tile);
      expect(windowOpen).toHaveBeenCalledWith(
        'https://google.com/travel/hotels/canal-house',
        '_blank',
        'noopener,noreferrer'
      );
      expect(onOpenSheet).toHaveBeenCalledWith('dates');
      expect(onClose).toHaveBeenCalledTimes(2);

      unmount();
      expect(document.body.style.overflow).toBe('');
    });
  });

  describe('SuggestionCard', () => {
    beforeEach(() => {
      suggestionCardMocks.trackDeeplinkClick.mockReset();
    });

    it('covers compact and expanded suggestion render paths', () => {
      const onSave = vi.fn();
      const compactTile = buildTile({
        id: 'stay_1',
        deeplink_url: 'https://www.viator.com/tours/amsterdam/canal-house',
        price_estimate: 320,
        meta: {
          amenities: ['Breakfast included', 'Pool'],
        },
      });

      const { rerender } = render(
        <SuggestionCard
          tile={compactTile}
          isSaved={true}
          onSave={onSave}
          variant="compact"
        />
      );

      expect(screen.getByText('Suggested')).toBeInTheDocument();
      expect(screen.getByText('★★★★★')).toBeInTheDocument();
      expect(screen.getByText('Canal House')).toBeInTheDocument();
      expect(screen.getByText('Amsterdam Center')).toBeInTheDocument();
      expect(screen.getByText('$320')).toBeInTheDocument();
      expect(screen.getByText('/night')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('link', { name: /book/i }));
      fireEvent.click(screen.getByRole('button', { name: /remove from trip/i }));

      expect(suggestionCardMocks.trackDeeplinkClick).toHaveBeenCalledWith('stay_1');
      expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ id: 'stay_1' }));

      const expandedTile = buildTile({ id: 'stay_2', title: 'Jordaan Loft' });
      const onDetailsClick = vi.fn();
      rerender(
        <SuggestionCard
          tile={expandedTile}
          reasoning="Walkable to the canals and cafe-heavy streets."
          isSaved={true}
          onSave={onSave}
          onDetailsClick={onDetailsClick}
          variant="expanded"
          className="test-card"
        />
      );

      expect(screen.getByText('Jordaan Loft')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /why this suggestion/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Change' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'View Details' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Saved' })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /why this suggestion/i }));
      expect(screen.getByText('Walkable to the canals and cafe-heavy streets.')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'View Details' }));
      expect(onDetailsClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'stay_2' }));
    });
  });
});

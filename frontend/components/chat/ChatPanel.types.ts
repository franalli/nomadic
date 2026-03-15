import type {
  ActivitySettings,
  BookingTypes,
  DocumentBranch,
  DocumentTripInputs,
  FlightSettings,
  GraphPlanResponse,
  HotelSettings,
} from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

export interface ChatPanelProps {
  selectedBranchId: string | null;
  onGeneratePlanStart?: () => void;
  onAutoExpandItinerary?: (options?: { forceFullRebuild?: boolean }) => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: DocumentTripInputs | null;
    readyToGenerate?: boolean;
    response?: GraphPlanResponse;
  }) => void;
  fullHeight?: boolean;
  hasBranches?: boolean;
  readyToGenerate?: boolean;
  isGenerating?: boolean;
  planState?: 'INCOMPLETE' | 'RESOLVING' | 'STABLE' | 'LOCKED';
  destination?: string;
  origin?: string;
  dateRange?: string;
  budget?: string;
  hasDestination?: boolean;
  hasDates?: boolean;
  tripInputs?: DocumentTripInputs;
  bookingTypes?: BookingTypes;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  activitySettings?: ActivitySettings;
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  onUpdateHotelSettings?: (settings: Partial<HotelSettings>) => void;
  onUpdateActivitySettings?: (settings: Partial<ActivitySettings>) => void;
  planViewState?: PlanViewState | null;
  isFraming?: boolean;
  onOpenSheet?: (sheet: SheetType) => void;
  destinationImageUrl?: string | null;
  onUserMessageSubmit?: (message: string) => void;
  onConfirmReset?: () => void;
}

export interface ChatPanelHandle {
  sendMessage: (message: string) => Promise<void>;
  addAssistantMessage: (message: string) => void;
  stopStreaming: () => void;
}

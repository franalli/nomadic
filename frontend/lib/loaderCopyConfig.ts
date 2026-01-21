/**
 * Loader copy configuration.
 * Defines action-specific titles and subtext sequences for the progress loader.
 */

import type {
  LoaderActionType,
  LoaderCopyConfig,
  VerticalFetchType,
} from '@/types/loader';

/**
 * Copy configuration for each action type.
 * Subtexts progress automatically during the operation.
 */
export const LOADER_COPY: Record<LoaderActionType, LoaderCopyConfig> = {
  generate_plan: {
    title: 'Building your plan',
    subtexts: [
      'Understanding your trip…',
      'Building a trip strategy…',
      'Finding deals…',
      'Finalizing…',
    ],
    fallbackSubtext: 'Still working…',
  },
  update_plan: {
    title: 'Updating your plan',
    subtexts: [
      'Applying your changes…',
      'Rebuilding strategy…',
      'Refreshing deals…',
    ],
    fallbackSubtext: 'Almost done…',
  },
  refresh_deals: {
    title: 'Refreshing deals',
    subtexts: [], // Dynamic based on hasTiles - see getRefreshDealsCopy()
    fallbackSubtext: 'Still searching…',
  },
  create_itinerary: {
    title: 'Creating your itinerary',
    subtexts: [
      'Drafting day-by-day plan…',
      'Optimizing timing and logistics…',
      'Finalizing booking-ready plan…',
    ],
    fallbackSubtext: 'Still building your itinerary…',
  },
  vertical_fetch: {
    title: '', // Dynamic based on verticalType - see VERTICAL_FETCH_COPY
    subtexts: [],
  },
};

/**
 * Copy configuration for vertical fetch sub-types.
 */
export const VERTICAL_FETCH_COPY: Record<VerticalFetchType, LoaderCopyConfig> = {
  flights: {
    title: 'Finding flights',
    subtexts: ['Searching routes and fares…'],
  },
  stays: {
    title: 'Finding stays',
    subtexts: ['Searching places to stay…'],
  },
  activities: {
    title: 'Finding activities',
    subtexts: ['Curating experiences…'],
  },
};

/**
 * Get copy config for refresh_deals based on whether tiles already exist.
 */
export function getRefreshDealsCopy(hasTiles: boolean): LoaderCopyConfig {
  return {
    title: 'Refreshing deals',
    subtexts: [hasTiles ? 'Checking latest prices…' : 'Searching deals…'],
    fallbackSubtext: 'Still searching…',
  };
}

/**
 * Get the appropriate copy config for an action.
 */
export function getLoaderCopy(
  actionType: LoaderActionType,
  options?: {
    verticalType?: VerticalFetchType;
    hasTiles?: boolean;
  }
): LoaderCopyConfig {
  if (actionType === 'vertical_fetch' && options?.verticalType) {
    return VERTICAL_FETCH_COPY[options.verticalType];
  }
  if (actionType === 'refresh_deals') {
    return getRefreshDealsCopy(options?.hasTiles ?? false);
  }
  return LOADER_COPY[actionType];
}

/**
 * Step duration in milliseconds for subtext progression.
 * Subtexts advance every STEP_DURATION_MS during the operation.
 */
export const STEP_DURATION_MS = 2000;

/**
 * Fallback timeout in milliseconds.
 * After this duration, show fallbackSubtext if available.
 */
export const FALLBACK_TIMEOUT_MS = 30000;

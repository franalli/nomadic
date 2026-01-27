import { useDocumentTripInputs } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';

/**
 * Hook that returns trip inputs from store with prop fallback.
 *
 * Ensures components always have fresh data even if prop-drilling breaks.
 * Priority: Store (Live) > Props (Parent passed) > undefined
 *
 * This is a safety net for components that receive tripInputs as props
 * but should always show the latest data from the store.
 *
 * @param propInputs - Optional trip inputs passed as props from parent
 * @returns Trip inputs from store, or props as fallback, or undefined
 *
 * @example
 * ```tsx
 * function MyComponent(props: { tripInputs?: DocumentTripInputs }) {
 *   // Always gets fresh data, even if parent doesn't re-render
 *   const tripInputs = useTripInputsWithFallback(props.tripInputs);
 *   // ...
 * }
 * ```
 */
export function useTripInputsWithFallback(
  propInputs?: DocumentTripInputs | null
): DocumentTripInputs | undefined {
  const storeInputs = useDocumentTripInputs();
  return storeInputs ?? propInputs ?? undefined;
}

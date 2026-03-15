'use client';

import { useSyncExternalStore } from 'react';

import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';

const NOOP_UNSUBSCRIBE = () => {};
const NOOP_SUBSCRIBE = () => NOOP_UNSUBSCRIBE;

/**
 * Hook that returns trip inputs from store with prop fallback.
 *
 * When props are present, avoid subscribing to the store so hot/root
 * planning surfaces do not rerender on unrelated trip input mutations.
 * Priority: Props (Parent passed) > Store (Live fallback) > undefined
 *
 * This stays a safety net for components that do not receive tripInputs
 * from their parent: those still subscribe to the live store.
 *
 * @param propInputs - Optional trip inputs passed as props from parent
 * @returns Trip inputs from props, or store fallback, or undefined
 *
 * @example
 * ```tsx
 * function MyComponent(props: { tripInputs?: DocumentTripInputs }) {
 *   // Prefer prop-backed inputs without subscribing to the store
 *   const tripInputs = useTripInputsWithFallback(props.tripInputs);
 *   // ...
 * }
 * ```
 */
export function useTripInputsWithFallback(
  propInputs?: DocumentTripInputs | null
): DocumentTripInputs | undefined {
  return useSyncExternalStore(
    propInputs ? NOOP_SUBSCRIBE : useDocumentStore.subscribe,
    () => propInputs ?? useDocumentStore.getState().document?.trip_inputs ?? undefined,
    () => propInputs ?? useDocumentStore.getState().document?.trip_inputs ?? undefined
  );
}

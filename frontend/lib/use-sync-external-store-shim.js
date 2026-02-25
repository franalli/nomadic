import { useSyncExternalStore } from 'react';

export function useSyncExternalStoreWithSelector(
  subscribe,
  getSnapshot,
  getServerSnapshot,
  selector = (value) => value
) {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return selector(snapshot);
}

export default {
  useSyncExternalStoreWithSelector,
};

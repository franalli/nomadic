import { create } from 'zustand';

import { apiFetch } from '@/lib/api';

export interface AuthUser {
  id: number;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

export interface UserTripSummary {
  trip_id: number;
  destination: string | null;
  start_date: string | null;
  end_date: string | null;
  day_count: number;
  updated_at: string;
  plan_view_state: string | null;
}

interface UserState {
  user: AuthUser | null;
  trips: UserTripSummary[];
  loading: boolean;
  resumingTripId: number | null;
  fetchUser: () => Promise<void>;
  fetchTrips: (opts?: { force?: boolean }) => Promise<void>;
  resumeTrip: (tripId: number) => Promise<boolean>;
  login: () => Promise<void>;
  logout: () => Promise<void>;
}

const TRIPS_STALE_MS = 30_000;
let tripsInFlight: Promise<void> | null = null;
let tripsLastFetchedAt = 0;

export const useUserStore = create<UserState>((set, get) => ({
  user: null,
  trips: [],
  loading: true,
  resumingTripId: null,

  fetchUser: async () => {
    try {
      const res = await apiFetch('/api/auth/me');
      if (!res.ok) throw new Error('Failed to fetch user');
      const data = await res.json();
      set({ user: data?.user ?? null, loading: false });
    } catch {
      set({ user: null, loading: false });
    }
  },

  fetchTrips: async ({ force = false } = {}) => {
    if (!force && Date.now() - tripsLastFetchedAt < TRIPS_STALE_MS) {
      return;
    }
    if (tripsInFlight) {
      await tripsInFlight;
      return;
    }
    tripsInFlight = (async () => {
      try {
        const res = await apiFetch('/api/trips');
        if (res.status === 401) {
          set({ trips: [] });
          tripsLastFetchedAt = Date.now();
          return;
        }
        if (!res.ok) throw new Error('Failed to fetch trips');
        const data = await res.json();
        set({ trips: Array.isArray(data?.trips) ? data.trips : [] });
        tripsLastFetchedAt = Date.now();
      } catch {
        set({ trips: [] });
      } finally {
        tripsInFlight = null;
      }
    })();
    await tripsInFlight;
  },

  resumeTrip: async (tripId: number) => {
    if (get().resumingTripId !== null) return false;
    set({ resumingTripId: tripId });
    try {
      const res = await apiFetch(`/api/trips/${tripId}/resume`, { method: 'POST' });
      if (!res.ok) {
        set({ resumingTripId: null });
        return false;
      }
      window.location.reload();
      return true;
    } catch {
      set({ resumingTripId: null });
      return false;
    }
  },

  login: async () => {
    const res = await apiFetch('/api/auth/google/url');
    if (!res.ok) throw new Error('Failed to initialize login');
    const data = await res.json();
    if (!data?.url || typeof data.url !== 'string') {
      throw new Error('Login URL missing');
    }
    window.location.href = data.url;
  },

  logout: async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } finally {
      set({ user: null, trips: [] });
      tripsLastFetchedAt = 0;
    }
  },
}));

/**
 * Popular destinations and origins for empty-state UI affordances.
 *
 * These are tap-to-fill shortcuts shown when the search field is empty.
 * They are personalization seeds only — the user types over them.
 * Keep this list small (≤8) and globally recognizable.
 *
 * Future: replace with user-history-based suggestions from the backend.
 */

export const POPULAR_DESTINATIONS = [
  { name: 'Paris, France', iata: 'CDG' },
  { name: 'Tokyo, Japan', iata: 'NRT' },
  { name: 'New York, USA', iata: 'JFK' },
  { name: 'London, UK', iata: 'LHR' },
  { name: 'Dubai, UAE', iata: 'DXB' },
  { name: 'Barcelona, Spain', iata: 'BCN' },
  { name: 'Rome, Italy', iata: 'FCO' },
  { name: 'Bali, Indonesia', iata: 'DPS' },
] as const;

export const POPULAR_ORIGINS = [
  { name: 'New York', iata: 'JFK' },
  { name: 'Los Angeles', iata: 'LAX' },
  { name: 'London', iata: 'LHR' },
  { name: 'Chicago', iata: 'ORD' },
  { name: 'San Francisco', iata: 'SFO' },
  { name: 'Miami', iata: 'MIA' },
  { name: 'Boston', iata: 'BOS' },
  { name: 'Seattle', iata: 'SEA' },
] as const;

'use client';

import { useState } from 'react';

import { TileCard } from '@/components/tiles/TileCard';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/lib/api';

type Tile = {
  id: string;
  type: string;
  title: string;
  subtitle?: string;
  image_url?: string;
  price_estimate?: number;
  currency: string;
  deeplink_url: string;
  rating?: number;
  location_label?: string;
};

export function ChatPanel() {
  const [origin, setOrigin] = useState('AMS');
  const [destination, setDestination] = useState('LIS');
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    setLoading(true);
    setError(null);

    try {
      const data = await apiFetch('/v1/tiles/search', {
        method: 'POST',
        body: JSON.stringify({
          origin,
          destination,
          verticals: ['hotel'],
          max_results_per_vertical: 4,
        }),
      });

      setTiles((data.tiles ?? []) as Tile[]);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Error contacting backend';
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <div className="flex gap-2">
        <input
          className="border-border flex-1 rounded-md border px-3 py-2 text-sm"
          placeholder="Origin (e.g. AMS)"
          value={origin}
          onChange={(e) => setOrigin(e.target.value.toUpperCase())}
        />
        <input
          className="border-border flex-1 rounded-md border px-3 py-2 text-sm"
          placeholder="Destination (e.g. LIS)"
          value={destination}
          onChange={(e) => setDestination(e.target.value.toUpperCase())}
        />
        <Button onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </Button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-2">
        {tiles.map((tile) => (
          <TileCard key={tile.id} tile={tile} />
        ))}
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { TileCard } from "@/components/tiles/TileCard";

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
  const [origin, setOrigin] = useState("AMS");
  const [destination, setDestination] = useState("LIS");
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        process.env.NEXT_PUBLIC_API_URL
          ? `${process.env.NEXT_PUBLIC_API_URL}/v1/tiles/search`
          : "http://localhost:8000/v1/tiles/search",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            origin,
            destination,
            verticals: ["hotel"],
            max_results_per_vertical: 4
          })
        }
      );
      if (!res.ok) {
        throw new Error(`Backend error: ${res.status}`);
      }
      const data = await res.json();
      setTiles(data.tiles || []);
    } catch (e: any) {
      setError(e.message ?? "Error contacting backend");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <div className="flex gap-2">
        <input
          className="flex-1 rounded-md border border-border px-3 py-2 text-sm"
          placeholder="Origin (e.g. AMS)"
          value={origin}
          onChange={(e) => setOrigin(e.target.value.toUpperCase())}
        />
        <input
          className="flex-1 rounded-md border border-border px-3 py-2 text-sm"
          placeholder="Destination (e.g. LIS)"
          value={destination}
          onChange={(e) => setDestination(e.target.value.toUpperCase())}
        />
        <Button onClick={handleSearch} disabled={loading}>
          {loading ? "Searching..." : "Search"}
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

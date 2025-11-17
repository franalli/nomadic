import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  requestId?: string;
  branchId?: string;
};

export function TileCard({ tile, requestId, branchId }: TileCardProps) {
  const handleClick = () => {
    // 1. Ensure we have a stable session_id
    let sessionId = localStorage.getItem('session_id');
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      localStorage.setItem('session_id', sessionId);
    }

    // 2. Fire-and-forget click tracking
    const numericBranchId = branchId && /^\d+$/.test(branchId) ? Number(branchId) : null;

    apiFetch('/v1/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId ?? null,
        tile_id: tile.id,
        branch_id: numericBranchId,
        session_id: sessionId,
        user_id: null,
      }),
    }).catch(() => {});

    // 3. Open partner deeplink immediately
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  };

  return (
    <Card className="flex flex-col overflow-hidden">
      {tile.image_url && (
        <img src={tile.image_url} alt={tile.title} className="h-32 w-full object-cover" />
      )}

      <CardBody className="flex flex-1 flex-col gap-1">
        <div className="text-sm font-semibold">{tile.title}</div>
        {tile.subtitle && <div className="text-xs text-slate-500">{tile.subtitle}</div>}
        {tile.location_label && (
          <div className="text-xs text-slate-500">{tile.location_label}</div>
        )}
        {tile.rating && (
          <div className="mt-1 text-xs text-slate-600">
            Rating: {tile.rating.toFixed(1)}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between pt-2">
          <div className="text-sm font-semibold">
            {tile.price_estimate != null
              ? `${tile.price_estimate} ${tile.currency}`
              : 'See price on partner'}
          </div>

          <Button variant="outline" className="text-xs" onClick={handleClick}>
            View
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type TileCardProps = {
  tile: {
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
};

export function TileCard({ tile }: TileCardProps) {
  return (
    <Card className="flex flex-col overflow-hidden">
      {tile.image_url && (
        <img
          src={tile.image_url}
          alt={tile.title}
          className="h-32 w-full object-cover"
        />
      )}
      <CardBody className="flex flex-1 flex-col gap-1">
        <div className="text-sm font-semibold">{tile.title}</div>
        {tile.subtitle && (
          <div className="text-xs text-slate-500">{tile.subtitle}</div>
        )}
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
              : "See price on partner"}
          </div>
          <Button
            variant="outline"
            className="text-xs"
            onClick={() => window.open(tile.deeplink_url, "_blank")}
          >
            View
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

import type { PlanBranch } from '@/types/plan';
import type { Tile, TileSelection } from '@/types/tile';

export type TripSummaryPayload = {
  branch: PlanBranch;
  selection: TileSelection;
  tiles: Tile[];
  note?: string | null;
  generatedAt: string;
};

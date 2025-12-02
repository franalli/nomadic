import type { DocumentBranch } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

export type TripSummaryPayload = {
  branch: DocumentBranch;
  selection: TileSelection;
  tiles: Tile[];
  note?: string | null;
  generatedAt: string;
};

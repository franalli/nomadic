export type PlanBranch = {
  id: string;
  label: string;
  description: string;
  destination: string;
};

export type PlanMeta = {
  primaryBranchId: string | null;
  tilesRequestId: string | null;
};

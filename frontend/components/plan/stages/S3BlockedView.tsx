/**
 * S3BlockedView
 *
 * Stage 3 blocked state - itinerary requested but gate failed.
 * Shows what's blocking and guides user to resolve.
 */

'use client';

import { Lock } from 'lucide-react';
import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';

interface S3BlockedViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
}

export function S3BlockedView({
  viewModel,
  destinationCard,
}: S3BlockedViewProps) {
  const { open_decisions = [] } = viewModel;
  const blockingDecisions = open_decisions.filter(d => d.is_blocking);

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Destination card */}
      {destinationCard && (
        <div className="bg-zinc-800/50 rounded-lg p-4 border border-zinc-700/50">
          <h2 className="text-lg font-medium text-zinc-100">
            {destinationCard.title}
          </h2>
          {destinationCard.subtitle && (
            <p className="text-sm text-zinc-400 mt-1">
              {destinationCard.subtitle}
            </p>
          )}
        </div>
      )}

      {/* Blocked indicator */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="bg-zinc-800/50 rounded-lg border border-zinc-700/50 p-6 max-w-sm text-center">
          <Lock className="w-8 h-8 text-zinc-500 mx-auto mb-3" />
          <h3 className="text-sm font-medium text-zinc-200 mb-2">
            Cannot generate itinerary yet
          </h3>
          <p className="text-xs text-zinc-400 mb-4">
            Some required information is still missing.
          </p>

          {/* Blocking items */}
          {blockingDecisions.length > 0 && (
            <div className="text-left bg-zinc-900/50 rounded-lg p-3">
              <p className="text-xs text-zinc-500 mb-2">Resolve these first:</p>
              <ul className="space-y-1.5">
                {blockingDecisions.map((decision) => (
                  <li
                    key={decision.id}
                    className="flex items-start gap-2 text-xs text-zinc-400"
                  >
                    <span className="text-zinc-600 mt-0.5">-</span>
                    <span>{decision.statement}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Hint */}
      <div className="text-center">
        <p className="text-zinc-500 text-xs">
          Provide the missing details to unlock itinerary
        </p>
      </div>
    </div>
  );
}

export default S3BlockedView;

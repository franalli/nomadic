/**
 * S2BlockedView
 *
 * Blocked state view - Stage 2 incomplete due to missing critical fields.
 * Shows what's missing and guides user to provide required information.
 */

'use client';

import { AlertTriangle } from 'lucide-react';

import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';

interface S2BlockedViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
}

export function S2BlockedView({
  viewModel,
  destinationCard: _destinationCard,
}: S2BlockedViewProps) {
  const { open_decisions = [] } = viewModel;
  const blockingDecisions = open_decisions.filter(d => d.is_blocking);

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Note: Destination card removed - PlanHeader owns destination display */}

      {/* Blocked indicator */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="bg-amber-900/30 rounded-lg border border-amber-700/40 p-6 max-w-sm text-center">
          <AlertTriangle className="w-8 h-8 text-amber-500 mx-auto mb-3" />
          <h3 className="text-sm font-medium text-amber-200 mb-2">
            Missing required information
          </h3>
          <p className="text-xs text-zinc-400 mb-4">
            We need a few more details before we can create your strategy.
          </p>

          {/* List blocking items */}
          {blockingDecisions.length > 0 && (
            <ul className="text-left space-y-2">
              {blockingDecisions.map((decision) => (
                <li
                  key={decision.id}
                  className="flex items-start gap-2 text-xs text-zinc-300"
                >
                  <span className="text-amber-500 mt-0.5">-</span>
                  <span>{decision.statement}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Hint */}
      <div className="text-center">
        <p className="text-zinc-500 text-xs">
          Update constraints in the chat to continue
        </p>
      </div>
    </div>
  );
}

export default S2BlockedView;

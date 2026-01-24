/**
 * CollapsedSetupSummary
 *
 * Single collapsed block replacing Setup assistant messages.
 * Shows: "Setup complete: Dubai · Jan 25-Feb 1 · 1 adult"
 * Expandable to show full conversation history.
 */

'use client';

import { ChevronDown, MessageSquare } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types/chat';

interface CollapsedSetupSummaryProps {
  summaryText: string;
  originalMessages?: ChatMessage[];
}

export function CollapsedSetupSummary({
  summaryText,
  originalMessages = [],
}: CollapsedSetupSummaryProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="mb-2">
      {/* Collapsed header */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 rounded-lg',
          'text-left text-xs transition-all duration-200',
          'bg-zinc-800/30 hover:bg-zinc-800/50',
          'border border-zinc-800/50',
          'group'
        )}
      >
        <MessageSquare className="h-3.5 w-3.5 text-zinc-500 flex-shrink-0" />
        <span className="flex-1 text-zinc-400 truncate">{summaryText}</span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-zinc-600 transition-transform duration-200',
            'group-hover:text-zinc-400',
            isExpanded && 'rotate-180'
          )}
        />
      </button>

      {/* Expanded conversation history */}
      {isExpanded && originalMessages.length > 0 && (
        <div
          className={cn(
            'mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50',
            'space-y-2 animate-in slide-in-from-top-2 duration-200'
          )}
        >
          {originalMessages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'text-xs',
                msg.role === 'user' ? 'text-zinc-300' : 'text-zinc-500'
              )}
            >
              <span className="text-zinc-600 font-medium">
                {msg.role === 'user' ? 'You: ' : 'Assistant: '}
              </span>
              {msg.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default CollapsedSetupSummary;

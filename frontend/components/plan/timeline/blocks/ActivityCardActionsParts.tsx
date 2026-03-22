'use client';

import { ExternalLink, MapPin } from 'lucide-react';

import { trackDeeplinkClick } from '@/lib/api-streaming';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// DeeplinkPill — emerald glass pill linking to partner booking or map
// ─────────────────────────────────────────────────────────────────────────────

interface DeeplinkPillProps {
  deeplink: string;
  tileId?: string;
}

export function DeeplinkPill({ deeplink, tileId }: DeeplinkPillProps) {
  const isViator = deeplink.includes('viator.com');
  const isGYG = deeplink.includes('getyourguide.com');
  const isPartner = isViator || isGYG;

  return (
    <a
      href={deeplink}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={isPartner ? (isViator ? 'Book on Viator' : 'Book on GetYourGuide') : 'Open map'}
      onClick={(e) => {
        e.stopPropagation();
        if (tileId) trackDeeplinkClick(tileId);
      }}
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-full px-3 py-2 self-start sm:self-center',
        'min-h-11',
        `${DS.textSize.micro} font-bold uppercase tracking-wider`,
        'transition-all duration-150 active:scale-95',
        'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
        'hover:bg-emerald-100 hover:border-emerald-500/60',
        'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
        'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
        `dark:hover:${DS.glowClass.chipHover}`,
      )}
    >
      {isPartner ? <ExternalLink className="w-3 h-3" /> : <MapPin className="w-3 h-3" />}
      {isPartner ? (
        <>
          <span className="sm:hidden">Book</span>
          <span className="hidden sm:inline">{isViator ? 'Book on Viator' : 'Book on GYG'}</span>
        </>
      ) : (
        'Map'
      )}
    </a>
  );
}

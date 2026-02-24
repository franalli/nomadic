/**
 * SmartLoader
 *
 * Part of the "Command & Receipt" pattern (DS Section 19.C).
 * A single mutating status line that shows the current processing state
 * with a dynamic icon. Cleaner than a scrolling log for consumer apps.
 */

'use client';

import {
  Brain, // router / extract_trip_fields
  Building2, // architect
  CalendarDays, // build_itinerary
  Loader2, // Default spinner
  type LucideIcon,
  MapPin, // local_expert / get_local_intel
  PenTool, // synthesizer
  Plane, // logistics / search_tiles
  Search, // search_tiles (alt)
  Shield, // guard / validate_plan
  Star, // specialist / get_specialist_advice
} from 'lucide-react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// Map backend 'icon_key' to Lucide components.
// Covers both v1 graph node keys and v2 tool-based keys.
const ICON_MAP: Record<string, LucideIcon> = {
  // v1 icon keys
  brain: Brain,
  building: Building2,
  plane: Plane,
  shield: Shield,
  pen: PenTool,
  star: Star,
  map: MapPin,
  // v2 icon keys (tools may emit these)
  search: Search,
  calendar: CalendarDays,
};

export interface ActiveStatus {
  label: string;
  icon_key?: string;
  detail?: string;
}

interface SmartLoaderProps {
  status: ActiveStatus;
}

export function SmartLoader({ status }: SmartLoaderProps) {
  // Resolve Icon (Defaults to Spinner if missing)
  const IconComponent = ICON_MAP[status.icon_key || ''] || Loader2;
  const displayText = status.detail || status.label;

  return (
    // Single line container - no bubble, just icon + text
    <div className="flex items-center gap-2 mb-2 ml-1 h-6 animate-in fade-in slide-in-from-bottom-1 duration-300">
      {/* 1. Dynamic Mutating Icon */}
      <IconComponent className="w-4 h-4 text-zinc-500 dark:text-emerald-500 animate-pulse" />

      {/* 2. Mutating Text - key triggers animation on change */}
      <span
        key={displayText}
        className={cn(
          `font-mono ${DS.textSize.micro} uppercase tracking-widest font-bold`,
          'text-zinc-600 dark:text-emerald-500/80',
          'animate-in fade-in slide-in-from-left-1 duration-300'
        )}
      >
        {displayText}
      </span>
    </div>
  );
}

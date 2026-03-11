'use client';
/**
 * S2TopicConfig
 *
 * Shared constants and helpers for S2 strategy view components.
 * No JSX — pure config, formatters, and utility functions.
 * Extracted from S2StrategyView to avoid circular imports across sub-components.
 */

import {
  Bike,
  Binoculars,
  Building,
  Mountain,
  Sailboat,
  Snowflake,
  Sparkles,
  Waves,
} from 'lucide-react';
import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { getSpecialistColorRgb } from '@/lib/specialists';

// ---------------------------------------------------------------------------
// Markdown helpers
// ---------------------------------------------------------------------------

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
};

/** Inline markdown text with rich formatting */
export function RichText({ children, className }: { children: string; className?: string }) {
  return (
    <span className={className}>
      <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {children}
      </Markdown>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Constraint title formatter
// ---------------------------------------------------------------------------

/** Format constraint keys to human-readable titles */
export const formatConstraintTitle = (rule: string): string => {
  const mappings: Record<string, string> = {
    'min_24h_buffer_after_dive': 'No-Fly Window (24h)',
    'min_18h_surface_interval': 'Surface Interval (18h)',
    'advanced_cert_required_for_deep': 'Depth Certification Limit',
    'altitude_acclimatization': 'Altitude Acclimatization',
    'proper_footwear_required': 'Footwear Required',
    'check_snow_conditions': 'Snow Conditions Check',
    'guide_required_offpiste': 'Guide Required (Off-Piste)',
    'feasibility_caveat': 'Location Advisory',
  };
  return mappings[rule] || rule.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// ---------------------------------------------------------------------------
// Topic priority and config
// ---------------------------------------------------------------------------

export const TOPIC_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  readyAction: string;
  updatingAction: string;
}> = {
  diving:         { icon: Waves,      label: 'Diving',         readyAction: 'Confirmed dive sites and safety intervals',       updatingAction: 'Checking dive site availability...' },
  hiking:         { icon: Mountain,   label: 'Hiking',         readyAction: 'Verified trail conditions and permits',           updatingAction: 'Checking seasonal trail access...' },
  skiing:         { icon: Snowflake,  label: 'Skiing',         readyAction: 'Verified resort conditions and lift passes',      updatingAction: 'Checking snow conditions...' },
  cycling:        { icon: Bike,       label: 'Cycling',        readyAction: 'Mapped routes and elevation profiles',            updatingAction: 'Analyzing route conditions...' },
  surfing:        { icon: Waves,      label: 'Surfing',        readyAction: 'Checked swell forecasts and beach conditions',    updatingAction: 'Checking surf conditions...' },
  climbing:       { icon: Mountain,   label: 'Climbing',       readyAction: 'Verified crag access and route grades',          updatingAction: 'Checking climbing conditions...' },
  sailing:        { icon: Sailboat,   label: 'Sailing',        readyAction: 'Confirmed marina availability and weather',       updatingAction: 'Checking marina schedules...' },
  wildlife_safari:{ icon: Binoculars, label: 'Wildlife Safari',readyAction: 'Verified game drive availability and seasons',    updatingAction: 'Checking safari conditions...' },
  local_expert:   { icon: Building,   label: 'Local Expert',   readyAction: 'Verified local logistics and booking requirements',updatingAction: 'Checking city constraints...' },
  general:        { icon: Sparkles,   label: 'General',        readyAction: 'Optimized itinerary and logistics',              updatingAction: 'Planning logistics...' },
};

export const DEFAULT_TOPIC_CONFIG = {
  icon: Sparkles,
  label: 'Specialist',
  readyAction: 'Analysis complete',
  updatingAction: 'Analyzing...',
};

// ---------------------------------------------------------------------------
// Color style cache
// ---------------------------------------------------------------------------

const TOPIC_COLOR_STYLE_CACHE = new Map<string, React.CSSProperties>();

export function getTopicColorStyle(topic: string): React.CSSProperties {
  const cached = TOPIC_COLOR_STYLE_CACHE.get(topic);
  if (cached) return cached;
  const style = { '--topic-color': getSpecialistColorRgb(topic) } as React.CSSProperties;
  TOPIC_COLOR_STYLE_CACHE.set(topic, style);
  return style;
}

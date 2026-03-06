'use client';
/**
 * StrategyHeroUtils
 *
 * Shared constants, utility functions, and icon helpers for StrategyHero components.
 * No component state — safe to import from any sub-component without circular deps.
 */

import {
  AlertCircle,
  Bike,
  Binoculars,
  Building,
  Clock,
  Info,
  Mountain,
  Sailboat,
  Snowflake,
  Sparkles,
  Waves,
} from 'lucide-react';
import React from 'react';

import { getSpecialistConfig } from '@/lib/specialists';
import type { StrategySection } from '@/types/plan-envelope';

// Lucide icon mapping from registry string names to components
export const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Waves, Mountain, Snowflake, Bike, Sailboat, Binoculars, Building, Sparkles,
};

export function getTopicIcon(specialistType: string): React.ComponentType<{ className?: string }> {
  const config = getSpecialistConfig(specialistType);
  if (config) return ICON_MAP[config.icon] || Sparkles;
  if (specialistType === 'local_expert') return Building;
  return Sparkles;
}

export function renderTopicIcon(specialistType: string, className?: string) {
  const Icon = getTopicIcon(specialistType);
  return <Icon className={className} />;
}

export function getTopicLabel(specialistType: string): string {
  const config = getSpecialistConfig(specialistType);
  if (config) return config.displayName;
  if (specialistType === 'local_expert') return 'Local Expert';
  if (specialistType === 'general') return 'General';
  return specialistType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Generic fallback image (specialist-specific hero images come from backend hero_image field)
export const GENERIC_FALLBACK_IMAGE =
  'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?q=80&w=2021&auto=format&fit=crop';

// Accordion icon Tailwind classes keyed by specialist type (component-local UI)
export const SPECIALIST_STYLE_CLASSES: Record<string, { light: string; icon: string }> = {
  diving: { light: 'bg-blue-50', icon: 'text-blue-600 dark:text-blue-400' },
  hiking: { light: 'bg-emerald-50', icon: 'text-emerald-600 dark:text-emerald-400' },
  skiing: { light: 'bg-blue-50', icon: 'text-blue-600 dark:text-blue-400' },
  sailing: { light: 'bg-cyan-50', icon: 'text-cyan-600 dark:text-cyan-400' },
  boating: { light: 'bg-cyan-50', icon: 'text-cyan-600 dark:text-cyan-400' },
  cycling: { light: 'bg-lime-50', icon: 'text-lime-600 dark:text-lime-400' },
  surfing: { light: 'bg-indigo-50', icon: 'text-indigo-600 dark:text-indigo-400' },
  climbing: { light: 'bg-orange-50', icon: 'text-orange-600 dark:text-orange-400' },
  wildlife_safari: { light: 'bg-amber-50', icon: 'text-amber-600 dark:text-amber-400' },
  local_expert: { light: 'bg-zinc-100', icon: 'text-zinc-600 dark:text-zinc-400' },
  general: { light: 'bg-emerald-50', icon: 'text-emerald-600 dark:text-emerald-400' },
};
export const DEFAULT_STYLE = { light: 'bg-zinc-50', icon: 'text-zinc-600 dark:text-zinc-400' };

/**
 * Get summary badge text showing content counts
 */
export function getSummaryBadge(section: StrategySection): string {
  const tipCount = (section.principles?.length || 0) + (section.content_added?.length || 0);
  // Only count blocking/strong constraints (not soft/info)
  const constraintCount = (section.constraints_applied || []).filter(c => {
    const sev = (c as Record<string, string>).severity;
    return !sev || sev === 'blocking' || sev === 'strong';
  }).length;
  const parts: string[] = [];
  if (tipCount > 0) parts.push(`${tipCount} tip${tipCount > 1 ? 's' : ''}`);
  if (constraintCount > 0) parts.push(`${constraintCount} constraint${constraintCount > 1 ? 's' : ''}`);
  return parts.join(' • ') || 'View details';
}

/**
 * Get friendly section label for constraints based on specialist type
 * These are system-inferred rules, not user-set constraints
 */
export function getConstraintSectionLabel(specialistType: string): string {
  const labels: Record<string, string> = {
    diving: 'Safety Requirements',
    hiking: 'Trail Safety',
    skiing: 'Mountain Safety',
    sailing: 'Maritime Safety',
    boating: 'Maritime Safety',
    cycling: 'Route Safety',
    surfing: 'Ocean Safety',
    climbing: 'Climbing Safety',
    wildlife_safari: 'Safari Safety',
    local_expert: 'Local Tips',
    general: 'Things to Know',
  };
  return labels[specialistType] || 'Safety & Constraints';
}

/**
 * Get concise badge text for constraint (3-4 words max)
 */
export function getShortConstraintLabel(rule: string): string {
  // Map common full rules to short labels
  const shortLabels: Record<string, string> = {
    'min_24h_buffer_after_dive': 'No-Fly 24h',
    'min_18h_surface_interval': 'Surface Interval',
    'advanced_cert_required_for_deep': 'Adv. Cert Needed',
    'altitude_acclimatization': 'Altitude Adjust',
    'proper_footwear_required': 'Proper Footwear',
    'check_snow_conditions': 'Snow Check',
    'guide_required_offpiste': 'Guide Required',
    'feasibility_caveat': 'Location Advisory',
    'cover_shoulders_and_knees_when_visiting_temples': 'Temple Dress Code',
    'rainy_season': 'Rainy Season',
    'strong_currents': 'Beach Safety',
  };

  // Check for direct match
  const lowerRule = rule.toLowerCase().replace(/ /g, '_');
  if (shortLabels[lowerRule]) {
    return shortLabels[lowerRule];
  }

  // Fallback: take first 3-4 words and capitalize
  const words = rule.replace(/_/g, ' ').split(' ').slice(0, 4);
  return words.map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
}

/**
 * Get the best available hero image from section data
 */
export function getHeroImage(section: StrategySection): string {
  // Priority 1: Backend-provided hero_image (for niche specialists)
  if (section.hero_image) {
    return section.hero_image;
  }

  // Priority 2: vibe_trio (General specialist - destination-specific images)
  if (section.vibe_trio?.[0]?.image_url) {
    return section.vibe_trio[0].image_url;
  }

  // Priority 3: destination_gallery (Local Expert)
  if (section.destination_gallery?.[0]?.image_url) {
    return section.destination_gallery[0].image_url;
  }

  // Priority 4: First content_added with image
  const contentImage = section.content_added?.find((c) => c.image_url)?.image_url;
  if (contentImage) {
    return contentImage;
  }

  // Priority 5: Generic fallback (specialist images come from backend hero_image field)
  return GENERIC_FALLBACK_IMAGE;
}

/**
 * Get constraint icon based on type
 */
export function getConstraintIcon(type: string) {
  if (type === 'safety' || type.includes('safety')) {
    return <AlertCircle className="w-3 h-3 text-amber-400" />;
  }
  if (type === 'temporal' || type.includes('time') || type.includes('buffer')) {
    return <Clock className="w-3 h-3 text-blue-400" />;
  }
  return <Info className="w-3 h-3 text-zinc-400" />;
}

/**
 * Format constraint rule to human-readable text
 */
export function formatConstraintRule(rule: string): string {
  return rule
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())
    .replace('Min ', '')
    .replace('Max ', '');
}

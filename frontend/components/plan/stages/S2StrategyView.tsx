/**
 * S2StrategyView
 *
 * Strategy ready state - shows stacked agent cards (one per topic) with color-coded UI.
 * This is the main planning view before itinerary generation.
 *
 * NOTE: This component renders CONTENT ONLY.
 * Header and CTAs are owned by StrategyStageRenderer.
 *
 * Agent status is COMPUTED from pending/executed topics, not stored on section.
 */

'use client';

import {
  AlertCircle,
  Bike,
  Binoculars,
  Briefcase,
  Building,
  ChevronDown,
  ChevronUp,
  CreditCard,
  Globe,
  Lightbulb,
  Mountain,
  Plug,
  Sailboat,
  Settings,
  ShieldCheck,
  Snowflake,
  Sparkles,
  Thermometer,
  Ticket,
  Train,
  Wallet,
  Waves,
  Wifi,
} from 'lucide-react';
import Image from 'next/image';
import React, { useCallback, useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { DS } from '@/lib/design-system';
import { getSpecialistColorRgb,SPECIALIST_IDS } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import {
  type AgentStatus,
  computeAgentStatus,
  type OpenDecision,
  type PlanViewModel,
  type StrategySection,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import type { DataDensity } from '../StrategyStageRenderer';
import { TripHealthBar } from '../TripHealthBar';
import { StrategyHero } from './StrategyHero';

// Markdown components for rich text rendering (emerald bold for key variables)
const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
};

// Helper component for inline markdown text
function RichText({ children, className }: { children: string; className?: string }) {
  return (
    <span className={className}>
      <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {children}
      </Markdown>
    </span>
  );
}

// Helper: Format constraint keys to human-readable titles
const formatConstraintTitle = (rule: string): string => {
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

// Topic priority: Local Expert first (foundation/logistics), then niche specialists, general last
const TOPIC_PRIORITY = ['local_expert', ...SPECIALIST_IDS, 'general'];

// Topic configuration with icons and UI copy (readyAction/updatingAction are component-local)
const TOPIC_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  readyAction: string;
  updatingAction: string;
}> = {
  diving: {
    icon: Waves,
    label: 'Diving',
    readyAction: 'Confirmed dive sites and safety intervals',
    updatingAction: 'Checking dive site availability...',
  },
  hiking: {
    icon: Mountain,
    label: 'Hiking',
    readyAction: 'Verified trail conditions and permits',
    updatingAction: 'Checking seasonal trail access...',
  },
  skiing: {
    icon: Snowflake,
    label: 'Skiing',
    readyAction: 'Verified resort conditions and lift passes',
    updatingAction: 'Checking snow conditions...',
  },
  cycling: {
    icon: Bike,
    label: 'Cycling',
    readyAction: 'Mapped routes and elevation profiles',
    updatingAction: 'Analyzing route conditions...',
  },
  surfing: {
    icon: Waves,
    label: 'Surfing',
    readyAction: 'Checked swell forecasts and beach conditions',
    updatingAction: 'Checking surf conditions...',
  },
  climbing: {
    icon: Mountain,
    label: 'Climbing',
    readyAction: 'Verified crag access and route grades',
    updatingAction: 'Checking climbing conditions...',
  },
  sailing: {
    icon: Sailboat,
    label: 'Sailing',
    readyAction: 'Confirmed marina availability and weather',
    updatingAction: 'Checking marina schedules...',
  },
  wildlife_safari: {
    icon: Binoculars,
    label: 'Wildlife Safari',
    readyAction: 'Verified game drive availability and seasons',
    updatingAction: 'Checking safari conditions...',
  },
  local_expert: {
    icon: Building,
    label: 'Local Expert',
    readyAction: 'Verified local logistics and booking requirements',
    updatingAction: 'Checking city constraints...',
  },
  general: {
    icon: Sparkles,
    label: 'General',
    readyAction: 'Optimized itinerary and logistics',
    updatingAction: 'Planning logistics...',
  },
};

const DEFAULT_TOPIC_CONFIG = {
  icon: Sparkles,
  label: 'Specialist',
  readyAction: 'Analysis complete',
  updatingAction: 'Analyzing...',
};

const TOPIC_COLOR_STYLE_CACHE = new Map<string, React.CSSProperties>();

function getTopicColorStyle(topic: string): React.CSSProperties {
  const cached = TOPIC_COLOR_STYLE_CACHE.get(topic);
  if (cached) return cached;
  const style = { '--topic-color': getSpecialistColorRgb(topic) } as React.CSSProperties;
  TOPIC_COLOR_STYLE_CACHE.set(topic, style);
  return style;
}

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  onRefineAssumptions?: () => void;
  /** Topics pending execution (for "Updating..." state) */
  pendingTopics?: string[];
  /** Topics that have been executed (from viewModel.executed_strategy_topics) */
  executedTopics?: string[];
  /** Tiles for TripHealthBar inventory counts */
  tiles?: Record<string, Tile>;
  /** Trip inputs for reactivity (store subscription provides live updates) */
  tripInputs?: DocumentTripInputs;
  /**
   * Data density level for adaptive rendering.
   * - 'bridge' / 'ghost': Use Accordion mode (collapsible inline)
   * - 'full': Use Compact mode (Trip DNA Bar)
   * - 'empty': Cards not rendered (handled by parent)
   * @see docs/ux_unified_architecture.md Section XII
   */
  density?: DataDensity;
  /**
   * Specialist type to expand (for chat-triggered expansion).
   * When this value changes to a valid specialist type, that card will be expanded.
   * Set to null/undefined to not trigger expansion.
   */
  expandSpecialistType?: string | null;
  /**
   * Whether to auto-expand cards on first load (3s preview then collapse).
   * - true (default for 'bridge'): Cards expand briefly then collapse
   * - false (default for 'ghost'): Cards stay collapsed
   * @default true for bridge density, false for ghost density
   */
  autoExpandOnLoad?: boolean;
  /** Callback to open activity settings sheet (for specialist gear icons) */
  onOpenActivitySettings?: () => void;
}

// =============================================================================
// LocalIntelSection - 2-Column "War Room" Layout for Local Expert
// =============================================================================

interface LocalIntelSectionProps {
  section: StrategySection;
}

/** Badge types for color-coding */
type BadgeType = 'logistics' | 'essential' | 'sells_out' | 'attraction';

/** Badge component with high-contrast dark mode colors */
function IntelBadge({ type, label }: { type: BadgeType; label: string }) {
  const styles: Record<BadgeType, string> = {
    logistics: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    essential: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    sells_out: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
    attraction: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  };

  return (
    <span className={cn(`${DS.textSize.micro} font-bold px-2 py-0.5 rounded uppercase tracking-wide`, styles[type])}>
      {label}
    </span>
  );
}

/** Intel card with icon, title, badge, and description */
interface IntelCardProps {
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  title: string;
  badge: { type: BadgeType; label: string };
  description: string;
  /** Amber border for high-priority items */
  isHighPriority?: boolean;
}

function IntelCard({ icon: Icon, iconColor, title, badge, description, isHighPriority }: IntelCardProps) {
  return (
    <div
      className={cn(
        'p-3 rounded-xl border transition-colors',
        isHighPriority
          ? 'border-red-200 bg-red-50 dark:border-red-800/40 dark:bg-red-900/10'
          : 'border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900'
      )}
    >
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
          <Icon className={cn('w-4 h-4', iconColor)} />
          <span className="font-bold text-zinc-900 dark:text-zinc-100 text-sm">{title}</span>
        </div>
        <IntelBadge type={badge.type} label={badge.label} />
      </div>
      <p
        className={cn(
          'text-xs leading-relaxed',
          isHighPriority ? 'text-zinc-600 dark:text-zinc-300' : 'text-zinc-500 dark:text-zinc-400'
        )}
        dangerouslySetInnerHTML={{ __html: description }}
      />
    </div>
  );
}

/**
 * Extracts logistics items from section content.
 * These are "survival" items: transport, connectivity, payments, power, visa.
 */
function extractLogisticsItems(section: StrategySection) {
  const logisticsTypes = ['transport', 'logistics', 'metro', 'connectivity', 'sim', 'wifi', 'payment', 'currency', 'plug', 'power', 'visa'];

  const items = section.content_added?.filter((c) => {
    const typeMatch = logisticsTypes.some((t) => c.type?.toLowerCase().includes(t));
    const titleMatch = logisticsTypes.some((t) => c.title?.toLowerCase().includes(t));
    return typeMatch || titleMatch;
  });

  return items || [];
}

/**
 * Extracts attraction/booking items from section content.
 * These are "experience" items that may need advance booking.
 */
function extractAttractionItems(section: StrategySection) {
  const attractionTypes = ['attraction', 'activity', 'experience', 'museum', 'landmark', 'restaurant'];

  const items = section.content_added?.filter((c) => {
    const typeMatch = attractionTypes.some((t) => c.type?.toLowerCase().includes(t));
    const hasBookHook = c.logic_hook?.includes('BOOK');
    // Include if it's an attraction type OR has a booking requirement
    return typeMatch || hasBookHook;
  });

  return items || [];
}

/**
 * Gets appropriate icon for a logistics item based on keywords.
 */
function getLogisticsIcon(item: { title: string; type?: string }) {
  const text = `${item.title} ${item.type || ''}`.toLowerCase();
  if (text.includes('metro') || text.includes('transport') || text.includes('train')) return { icon: Train, color: 'text-blue-500' };
  if (text.includes('sim') || text.includes('wifi') || text.includes('connect')) return { icon: Wifi, color: 'text-blue-500' };
  if (text.includes('payment') || text.includes('card') || text.includes('cash')) return { icon: CreditCard, color: 'text-blue-500' };
  if (text.includes('plug') || text.includes('power') || text.includes('electric')) return { icon: Plug, color: 'text-blue-500' };
  if (text.includes('visa') || text.includes('passport')) return { icon: Globe, color: 'text-blue-500' };
  if (text.includes('weather') || text.includes('climate')) return { icon: Thermometer, color: 'text-blue-500' };
  if (text.includes('currency') || text.includes('money')) return { icon: Wallet, color: 'text-blue-500' };
  return { icon: Lightbulb, color: 'text-blue-500' };
}

/**
 * Gets appropriate icon for an attraction item based on keywords.
 */
function getAttractionIcon(item: { title: string; type?: string }) {
  const text = `${item.title} ${item.type || ''}`.toLowerCase();
  if (text.includes('museum')) return { icon: Building, color: 'text-purple-500' };
  if (text.includes('restaurant') || text.includes('food')) return { icon: Sparkles, color: 'text-purple-500' };
  return { icon: Ticket, color: 'text-red-500' };
}

/**
 * LocalIntelSection - Renders the 2-column "War Room" layout for Local Expert cards.
 *
 * Layout:
 * - Left Column: "Logistics & Survival" (transport, connectivity, payments, power)
 * - Right Column: "Booking Radar" (attractions that sell out)
 *
 * Color-coded badges for dark mode visibility:
 * - Blue: Logistics/Essential
 * - Amber: Sells Out warnings
 * - Purple: Standard attractions
 */
function LocalIntelSection({ section }: LocalIntelSectionProps) {
  const logisticsItems = extractLogisticsItems(section);
  const attractionItems = extractAttractionItems(section);

  // Also include logistics_notes as fallback logistics items
  const hasLogisticsNotes = section.logistics_notes && section.logistics_notes.length > 0;

  // Check if we have any content to show
  const hasContent = logisticsItems.length > 0 || attractionItems.length > 0 || hasLogisticsNotes;

  if (!hasContent) return null;

  return (
    <div className="space-y-4">
      {/* HEADER */}
      <div className="flex items-center gap-2">
        <Briefcase className="w-5 h-5 text-emerald-500" />
        <h3 className="text-base font-bold text-zinc-900 dark:text-white">Trip Operations Center</h3>
      </div>

      {/* 2-COLUMN WAR ROOM GRID */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* COLUMN 1: LOGISTICS TOOLKIT (The "How") */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest mb-2">
            Logistics & Survival
          </h4>

          {/* Render logistics items from content_added */}
          {logisticsItems.slice(0, 4).map((item, idx) => {
            const { icon, color } = getLogisticsIcon(item);
            const isEssential = item.logic_hook?.toLowerCase().includes('essential');
            return (
              <IntelCard
                key={`logistics-${idx}`}
                icon={icon}
                iconColor={color}
                title={item.title}
                badge={{ type: isEssential ? 'essential' : 'logistics', label: isEssential ? 'ESSENTIAL' : 'LOGISTICS' }}
                description={item.description || ''}
              />
            );
          })}

          {/* Fallback: Render logistics_notes if no structured logistics items */}
          {logisticsItems.length === 0 && hasLogisticsNotes && (
            <>
              {section.logistics_notes?.slice(0, 4).map((note, idx) => {
                const icons = [Globe, Thermometer, Plug, Wallet];
                const colors = ['text-blue-500', 'text-blue-500', 'text-blue-500', 'text-blue-500'];
                const titles = ['Visa', 'Weather', 'Power', 'Currency'];
                return (
                  <IntelCard
                    key={`note-${idx}`}
                    icon={icons[idx % icons.length]}
                    iconColor={colors[idx % colors.length]}
                    title={titles[idx % titles.length]}
                    badge={{ type: 'logistics', label: 'LOGISTICS' }}
                    description={note}
                  />
                );
              })}
            </>
          )}
        </div>

        {/* COLUMN 2: BOOKING RADAR (The "What") */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest mb-2">
            Booking Radar
          </h4>

          {/* Render attraction items */}
          {attractionItems.slice(0, 4).map((item, idx) => {
            const sellsOut = item.logic_hook?.toLowerCase().includes('sells out') || item.logic_hook?.includes('BOOK');
            const { icon, color } = sellsOut ? { icon: Ticket, color: 'text-red-500' } : getAttractionIcon(item);

            // Extract booking lead time if present
            const leadTimeMatch = item.logic_hook?.match(/(\d+\s*(?:days?|weeks?|hours?)\s*(?:ahead|prior)?)/i);
            const leadTime = leadTimeMatch?.[1];

            let description = item.description || '';
            if (leadTime && sellsOut) {
              description = `<strong>Action:</strong> Book ${leadTime}. ${description}`;
            }

            return (
              <IntelCard
                key={`attraction-${idx}`}
                icon={icon}
                iconColor={color}
                title={item.title}
                badge={{ type: sellsOut ? 'sells_out' : 'attraction', label: sellsOut ? 'SELLS OUT' : 'ATTRACTION' }}
                description={description}
                isHighPriority={sellsOut}
              />
            );
          })}

          {/* Empty state for booking radar */}
          {attractionItems.length === 0 && (
            <div className="p-4 rounded-xl border border-dashed border-zinc-200 dark:border-white/10 text-center">
              <p className="text-xs text-zinc-400 dark:text-zinc-500">
                No advance booking items detected
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// AgentCard - Single agent card with topic color system
// =============================================================================

interface AgentCardProps {
  section: StrategySection;
  isExpanded: boolean;
  onToggle: () => void;
  status: AgentStatus;
  /** Whether trip dates are set (for showing "add dates" hint) */
  hasDates?: boolean;
  /** Callback to open activity settings sheet (for specialist cards) */
  onOpenSettings?: () => void;
}

function AgentCard({ section, isExpanded, onToggle, status, hasDates = true, onOpenSettings }: AgentCardProps) {
  const cardRef = React.useRef<HTMLDivElement>(null);

  // Scroll card into view when expanded (prevents jumping to wrong location)
  React.useEffect(() => {
    if (isExpanded && cardRef.current) {
      // Small delay to allow content to render
      const timer = setTimeout(() => {
        cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isExpanded]);

  // Fallback logic for backward compatibility with legacy responses
  const oneLiner = section.one_liner || section.bullets[0] || '';
  const principles =
    section.principles && section.principles.length > 0
      ? section.principles
      : section.bullets.slice(0, 3);

  const topic = section.specialist_type || 'general';
  const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
  const Icon = config.icon;

  // Feasibility state from Constraint Engine
  const isInfeasible = section.feasibility_status === 'infeasible';
  const hasCaveat = section.feasibility_status === 'caveat';

  return (
    // 1. data-topic attribute for CSS color system
    // 2. Left accent border (3px, strong color)
    // 3. Infeasible/caveat border colors
    <div
      ref={cardRef}
      data-topic={topic}
      style={getTopicColorStyle(topic)}
      className={cn(
        "rounded-2xl border overflow-hidden topic-border-left transition-all duration-200",
        // Light: Pure white card with premium soft shadow
        "bg-white shadow-[0_2px_8px_-2px_rgba(0,0,0,0.05)]",
        // Dark: Solid panel with clear boundary
        "dark:bg-zinc-900 dark:shadow-none",
        // State-based borders
        isInfeasible && "border-red-500/50 bg-red-950/10",
        hasCaveat && "border-zinc-400/30",
        // Default: Crisp border with hover enhancement
        !isInfeasible && !hasCaveat && "border-zinc-200 hover:border-emerald-500/30 hover:shadow-[0_4px_12px_-4px_rgba(0,0,0,0.08)] dark:border-zinc-800"
      )}
    >
      {/* 3. Header with subtle tint - group for hover effects */}
      <button
        onClick={onToggle}
        className={cn(
          "w-full px-5 py-4 text-left transition-all duration-200 group",
          isInfeasible ? "bg-red-950/20 hover:bg-red-950/30" : "topic-header-tint hover:bg-zinc-50 dark:hover:bg-muted/30",
          // Active/tap feedback
          "active:scale-[0.995]"
        )}
      >
        {/* Row 1: Specialist badge + Status chip + Plan/Booking badges */}
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            {/* Topic badge with icon (strong color, or red if infeasible) */}
            <span className={cn(
              "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium",
              isInfeasible ? "bg-red-500/20 text-red-400" : "topic-badge"
            )}>
              <Icon className="w-3 h-3" />
              {config.label} Specialist
            </span>

            {/* Infeasible badge */}
            {isInfeasible && (
              <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded font-medium uppercase tracking-wider`}>
                Unavailable
              </span>
            )}

            {/* Caveat badge */}
            {hasCaveat && (
              <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-zinc-500/20 text-zinc-400 rounded font-medium`}>
                Limited
              </span>
            )}

            {/* Status chip - only show when updating or needs input (presence of content implies ready) */}
            {!isInfeasible && status !== 'ready' && (
              <span className={cn(
                `${DS.textSize.micro} px-2 py-1 rounded-full font-bold uppercase tracking-wide`,
                // Updating: Emerald pulse (per design system)
                status === 'updating' && "bg-emerald-50 text-emerald-700 border border-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-transparent animate-pulse",
                // Needs input: Subtle muted
                status === 'needs_input' && "bg-zinc-100 text-zinc-500 dark:bg-muted dark:text-muted-foreground"
              )}>
                {status === 'updating' ? 'Updating...' : 'Needs input'}
              </span>
            )}
          </div>
          {/* Right side: Settings gear (specialists only) + Chevron */}
          {!isInfeasible && (
            <div className="flex items-center gap-1.5">
              {/* Settings gear - only for specialist cards */}
              {onOpenSettings && ['diving', 'hiking', 'skiing', 'cycling', 'sailing'].includes(topic) && (
                <div
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenSettings();
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.stopPropagation();
                      onOpenSettings();
                    }
                  }}
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center shrink-0 cursor-pointer",
                    "bg-zinc-100 hover:bg-zinc-200 dark:bg-white/5 dark:hover:bg-white/10",
                    "transition-all duration-200"
                  )}
                  title="Activity settings"
                >
                  <Settings className="w-4 h-4 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
                </div>
              )}
              {/* Chevron with circular touch target */}
              <div className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center shrink-0",
                "bg-zinc-50 hover:bg-zinc-100 dark:bg-white/5 dark:hover:bg-white/10",
                "transition-all duration-200"
              )}>
                <ChevronDown className={cn(
                  "w-4 h-4 transition-transform duration-200",
                  "text-zinc-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400",
                  isExpanded && "rotate-180"
                )} />
              </div>
            </div>
          )}
        </div>

        {/* Infeasible reason message */}
        {isInfeasible && section.feasibility_reason && (
          <div className="mt-2 text-xs text-red-400">
            <RichText>{section.feasibility_reason}</RichText>
          </div>
        )}

        {/* Alternative suggestion for infeasible */}
        {isInfeasible && section.alternative_suggestion && (
          <div className={`mt-1 ${DS.textSize.micro} text-muted-foreground`}>
            💡 <RichText>{section.alternative_suggestion}</RichText>
          </div>
        )}

        {/* Caveat warning message */}
        {hasCaveat && section.feasibility_reason && (
          <div className="mt-2 text-xs text-zinc-500 flex items-center gap-1">
            <span>⚠️</span>
            <RichText>{section.feasibility_reason}</RichText>
          </div>
        )}

        {/* Mini-log: Last action performed by this specialist (not for infeasible) */}
        {!isInfeasible && status !== 'needs_input' && (
          <div className={`mt-1.5 flex items-center gap-1.5 ${DS.textSize.micro} text-muted-foreground`}>
            <span className={cn(
              status === 'ready' ? 'text-green-600 dark:text-green-400' : 'text-emerald-600 dark:text-emerald-400'
            )}>
              {status === 'ready' ? '✓' : '○'}
            </span>
            <span className="text-sm text-zinc-500 dark:text-zinc-400">
              {status === 'ready' ? config.readyAction : config.updatingAction}
            </span>
          </div>
        )}

        {/* Hint: Add dates to unlock full recommendations (when specialist ran without dates) */}
        {!isInfeasible && status === 'ready' && !hasDates && (
          <div className={`mt-1 flex items-center gap-1.5 ${DS.textSize.micro} text-zinc-500`}>
            <span>📅</span>
            <span>Add dates to unlock day-by-day scheduling</span>
          </div>
        )}

        {/* Expand hint - shows when collapsed to signal interactivity */}
        {!isExpanded && !isInfeasible && (
          <p className={`mt-2 ${DS.textSize.micro} font-medium text-emerald-600 dark:text-emerald-400 opacity-0 group-hover:opacity-100 transition-opacity`}>
            Tap to see expert details →
          </p>
        )}

        {/* Row 2 (collapsed): One-liner + principle chips (not for infeasible) */}
        {!isExpanded && !isInfeasible && (
          <div className="mt-2 w-full">
            {oneLiner && (
              <p className="text-xs text-muted-foreground mb-2"><RichText>{oneLiner}</RichText></p>
            )}
            {principles.length > 0 && (
              <div className="mt-3 space-y-2">
                {principles.slice(0, 4).map((p, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex items-start gap-3 p-2 rounded-lg transition-colors",
                      // Light: Clean hover state
                      "hover:bg-zinc-50",
                      // Dark: Subtle hover
                      "dark:hover:bg-zinc-800/30"
                    )}
                  >
                    {/* Bullet icon */}
                    <Lightbulb className="w-3.5 h-3.5 mt-0.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                    {/* Text - clean serif-like appearance */}
                    <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 font-medium">
                      {p}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </button>

      {/* Expanded content (normal bg-card, no tint) - NOT shown for infeasible */}
      {isExpanded && !isInfeasible && (
        <div className="px-4 pb-4 pt-2 border-t border-border/50 space-y-4">
          {/* Destination Gallery - "Vibe Trio" for Local Expert card */}
          {section.specialist_type === 'local_expert' && section.destination_gallery && section.destination_gallery.length > 0 && (
            <div className="mb-2">
              {/* MOBILE: Horizontal swipe carousel - larger, more prominent images */}
              <div className="flex gap-3 overflow-x-auto pb-3 snap-x no-scrollbar md:hidden">
                {section.destination_gallery.map((img, idx) => (
                  <div
                    key={idx}
                    className="shrink-0 snap-center relative w-64 h-40 rounded-xl overflow-hidden shadow-sm border border-zinc-200 dark:border-zinc-700/50"
                  >
                    <Image
                      src={img.image_url}
                      alt={img.label}
                      fill
                      className="object-cover"
                    />
                  </div>
                ))}
              </div>

              {/* DESKTOP: 3-column grid */}
              <div className="hidden md:grid grid-cols-3 gap-4">
                {section.destination_gallery.map((img, idx) => (
                  <div key={idx} className="relative h-48 md:h-64 rounded-xl overflow-hidden shadow-sm border border-zinc-100 dark:border-zinc-700/50 group">
                    <Image
                      src={img.image_url}
                      alt={img.label}
                      fill
                      className="object-cover transition-transform duration-500 group-hover:scale-105"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* LOCAL EXPERT: 4-Pillar Strategic Intel Section */}
          {section.specialist_type === 'local_expert' && (
            <LocalIntelSection section={section} />
          )}

          {/* Specialist Constraints: Readable metadata with icon bubbles */}
          {section.constraints_applied && section.constraints_applied.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 flex items-center gap-2">
                <ShieldCheck size={12} className="text-emerald-600 dark:text-emerald-400" /> Applied Constraints
              </h5>
              <div className="space-y-3">
                {section.constraints_applied.map((c, idx) => (
                  <div key={idx} className="flex items-start gap-3">
                    {/* Icon bubble - aligned to top */}
                    <div className="shrink-0 mt-0.5 w-5 h-5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 flex items-center justify-center">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    </div>
                    {/* Text content - darker for readability */}
                    <div className="space-y-0.5">
                      <p className="text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed font-medium">
                        {formatConstraintTitle(c.rule)}
                      </p>
                      {(c.reason || c.type) && (
                        <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                          {c.reason || c.type}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Expert Recommendations: The "Gems" - Logic-backed content with thumbnails */}
          {/* NOTE: Skip for local_expert since LocalIntelSection handles this content */}
          {section.content_added && section.content_added.length > 0 && section.specialist_type !== 'local_expert' && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 flex items-center gap-2">
                <Lightbulb size={12} className="text-emerald-600 dark:text-emerald-400" /> Expert Recommendations
              </h5>
              <div className="grid gap-3">
                {section.content_added.map((c, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "rounded-xl border transition-colors p-4 flex gap-3",
                      // Light: Clean white card with subtle shadow
                      "bg-white border-zinc-200 hover:border-emerald-500/30 shadow-sm",
                      // Dark: Glass panel
                      "dark:bg-zinc-900 dark:border-zinc-700 dark:hover:border-zinc-600 dark:shadow-none"
                    )}
                  >
                    {/* Thumbnail - Only render if image_url exists */}
                    {c.image_url && (
                      <div className="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0 bg-zinc-100 dark:bg-zinc-900">
                        <Image
                          src={c.image_url}
                          alt={c.title}
                          width={64}
                          height={64}
                          className="object-cover w-full h-full"
                        />
                      </div>
                    )}

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between items-start mb-1">
                        <span className="text-sm font-bold text-zinc-900 dark:text-white">{c.title}</span>
                        {c.type && (
                          <span className={`${DS.textSize.micro} font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded uppercase`}>
                            {c.type}
                          </span>
                        )}
                      </div>
                      {c.description && (
                        <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed line-clamp-2">
                          {c.description}
                        </p>
                      )}
                      {/* Logic Hook - The "Pro Tip" that proves deep knowledge */}
                      {c.logic_hook && (
                        <div className={cn(
                          `${DS.textSize.mini} mt-2.5 inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md border`,
                          // Light: Subtle emerald tint
                          "text-emerald-700 bg-emerald-50 border-emerald-200",
                          // Dark: Deep emerald glow
                          `dark:text-emerald-300 dark:bg-emerald-950 dark:border-emerald-700/60 dark:${DS.glowClass.badge}`
                        )}>
                          <Sparkles size={12} className="text-emerald-600 dark:text-emerald-400 flex-shrink-0 animate-pulse" />
                          <span className="font-medium tracking-wide">{c.logic_hook}</span>
                        </div>
                      )}
                      {c.day && (
                        <div className={`${DS.textSize.micro} text-muted-foreground mt-1.5`}>
                          Day {c.day}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Booking artifacts row - ONLY for general agent (specialists handle domain logic only) */}
          {section.booking_artifacts && section.specialist_type === 'general' && (
            <div className="flex flex-wrap gap-2 py-2 border-b border-border/30">
              <span className="text-xs text-muted-foreground">Booking surfaces:</span>
              {section.booking_artifacts.activities_count > 0 && (
                <span className="text-xs topic-bullet font-medium">
                  {section.booking_artifacts.activities_count} activities shortlisted
                </span>
              )}
              {section.booking_artifacts.hotels_count > 0 && (
                <span className="text-xs topic-bullet font-medium">
                  {section.booking_artifacts.hotels_count} hotels recommended
                </span>
              )}
            </div>
          )}

          {/* REMOVED: Must-dos section - content now shown in Expert Recommendations */}

          {/* Optional upgrades */}
          {section.optional_upgrades && section.optional_upgrades.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Optional upgrades
              </h5>
              <ul className="space-y-1.5">
                {section.optional_upgrades.slice(0, 3).map((item, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-muted-foreground flex items-start gap-2"
                  >
                    <span className="text-muted-foreground/70 mt-0.5">+</span>
                    <RichText>{item}</RichText>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Logistics notes */}
          {section.logistics_notes && section.logistics_notes.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Logistics
              </h5>
              <ul className="space-y-1.5">
                {section.logistics_notes.slice(0, 4).map((item, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-muted-foreground flex items-start gap-2"
                  >
                    <span className="text-muted-foreground/50 mt-0.5">-</span>
                    <RichText>{item}</RichText>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tradeoffs summary */}
          {section.tradeoffs_summary && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Why this approach
              </h5>
              <p className="text-xs text-muted-foreground">
                <RichText>{section.tradeoffs_summary}</RichText>
              </p>
            </div>
          )}

          {/* Impact areas */}
          {section.impact_areas && section.impact_areas.length > 0 && (
            <div className="flex items-center gap-2 pt-2 border-t border-border/30">
              <span className="text-xs text-muted-foreground">Impact:</span>
              {section.impact_areas.map((area, i) => (
                <span key={i} className="text-xs px-1.5 py-0.5 topic-badge rounded">
                  {area}
                </span>
              ))}
            </div>
          )}

          {/* Provenance (debug info) */}
          {(section.strategy_node_id || section.strategy_version) && (
            <details className={`${DS.textSize.micro} text-muted-foreground/70`}>
              <summary className="cursor-pointer">ⓘ Provenance</summary>
              <p className="mt-1 pl-2">
                Generated by: <span className="topic-bullet">{section.strategy_node_id}</span>
                {section.strategy_version && ` • v${section.strategy_version}`}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// StrategyStack - Stacked agent cards with overflow handling
// =============================================================================

interface StrategyStackProps {
  sections: StrategySection[];
  pendingTopics: string[];
  executedTopics: string[];
  /** Tiles for TripHealthBar inventory counts */
  tiles?: Record<string, Tile>;
  /** Whether trip dates are set (for showing "add dates" hint) */
  hasDates?: boolean;
  /** Callback to open activity settings sheet (for specialist gear icons) */
  onOpenActivitySettings?: () => void;
}

function StrategyStack({
  sections,
  pendingTopics,
  executedTopics,
  tiles = {},
  hasDates = true,
  onOpenActivitySettings,
}: StrategyStackProps) {
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [showAll, setShowAll] = React.useState(false);

  // Simple responsive check (can use proper hook if available)
  const [isMobile, setIsMobile] = React.useState(false);
  React.useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Extract General agent separately for TripHealthDashboard
  const generalSection = sections.find((s) => s.specialist_type === 'general');
  // Get non-general specialist sections
  const specialistSections = sections.filter((s) => s.specialist_type !== 'general');

  // BRIDGE MODE FIX: If no specialist sections exist but we have a general section,
  // show the general section as a regular card instead of filtering it out.
  // This ensures content is visible in Setup (Bridge) state before tiles are fetched.
  const hasTiles = Object.keys(tiles).length > 0;
  const hasSpecialists = specialistSections.length > 0;

  // In Bridge Mode (no tiles), show general as a card if no specialists exist
  // With tiles, general becomes TripHealthBar instead
  const filtered = hasSpecialists
    ? specialistSections  // Normal: show only specialists
    : sections;           // Bridge fallback: show all (including general)

  // Show TripHealthDashboard when General agent exists AND we have tiles
  // (In Bridge Mode without tiles, general renders as a card instead)
  const showTripHealth = generalSection && hasTiles;

  // Sort by topic priority for stable ordering
  const sorted = [...filtered].sort((a, b) => {
    const aIdx = TOPIC_PRIORITY.indexOf(a.specialist_type || 'general');
    const bIdx = TOPIC_PRIORITY.indexOf(b.specialist_type || 'general');
    return aIdx - bIdx;
  });

  // Filter out pending topics that already have sections (avoid duplicate cards)
  const filteredPendingTopics = pendingTopics.filter(
    topic => !sorted.some(section => section.specialist_type === topic)
  );

  // Apply visible limit
  const visibleLimit = isMobile ? 1 : 2;
  const visible = showAll ? sorted : sorted.slice(0, visibleLimit);
  const overflow = sorted.length - visibleLimit;

  // Reduced color mode for 3+ agents
  const useReducedColor = sorted.length > 2;

  // Check for pending topics
  const hasPending = filteredPendingTopics.length > 0;

  return (
    <div className="space-y-2" data-reduced-color={useReducedColor}>

      {/* Pending topics placeholder (updating state) */}
      {filteredPendingTopics.map(topic => {
        const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
        const TopicIcon = config.icon;
        return (
          <div
            key={`pending-${topic}`}
            data-topic={topic}
            style={getTopicColorStyle(topic)}
            className="bg-card rounded-lg border border-border px-4 py-3 topic-border-left"
          >
            <div className="flex items-center gap-2">
              <span className="topic-badge inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium">
                <TopicIcon className="w-3 h-3" />
                {config.label} Specialist
              </span>
              <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded font-medium animate-pulse`}>
                Updating...
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Generating strategy...</p>
          </div>
        );
      })}

      {/* Trip Health Bar (compact status bar from General agent - always at top) */}
      {showTripHealth && (
        <TripHealthBar
          tripSummary={generalSection?.trip_summary}
          tiles={tiles}
        />
      )}

      {/* Stacked specialist cards */}
      {visible.length > 0 ? (
        visible.map((section) => {
          const topic = section.specialist_type || 'general';
          const status = computeAgentStatus(topic, pendingTopics, executedTopics);
          return (
            <AgentCard
              key={section.id}
              section={section}
              isExpanded={expandedId === section.id}
              onToggle={() =>
                setExpandedId(expandedId === section.id ? null : section.id)
              }
              status={status}
              hasDates={hasDates}
              onOpenSettings={onOpenActivitySettings}
            />
          );
        })
      ) : (
        /* Clean state: No specialists yet, show subtle hint */
        !hasPending && showTripHealth && (
          <div className="text-center py-6 opacity-40">
            <p className="text-xs uppercase tracking-widest text-zinc-500 dark:text-zinc-400">System Ready</p>
            <p className={`${DS.textSize.micro} text-muted-foreground mt-1`}>
              Add activities like diving or hiking to see specialist logic
            </p>
          </div>
        )
      )}

      {/* Overflow expander */}
      {overflow > 0 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="text-xs text-primary hover:underline py-1"
        >
          +{overflow} more specialist{overflow > 1 ? 's' : ''}
        </button>
      )}
    </div>
  );
}

// =============================================================================
// OpenDecisionsPanel - Blocking/non-blocking decisions
// =============================================================================

function OpenDecisionsPanel({ decisions }: { decisions: OpenDecision[] }) {
  if (decisions.length === 0) return null;

  const blockingCount = decisions.filter((d) => d.is_blocking).length;

  return (
    <div className="bg-zinc-100 rounded-lg border border-zinc-200 p-4 dark:bg-zinc-900/50 dark:border-zinc-700/30">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
        <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-200">
          Open decisions
          {blockingCount > 0 && (
            <span className="text-zinc-600 dark:text-zinc-400 ml-1">
              ({blockingCount} blocking)
            </span>
          )}
        </h3>
      </div>
      <ul className="space-y-2">
        {decisions.slice(0, 4).map((decision) => (
          <li key={decision.id} className="flex items-start gap-2">
            <span
              className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                decision.is_blocking ? 'bg-zinc-900 dark:bg-white' : 'bg-muted-foreground/50'
              }`}
            />
            <span className="text-xs text-card-foreground">
              {decision.statement}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// =============================================================================
// S2StrategyView - Main export
// =============================================================================

export function S2StrategyView({
  viewModel,
  onRefineAssumptions,
  pendingTopics = [],
  executedTopics,
  tiles = {},
  tripInputs: propTripInputs,
  density,
  expandSpecialistType,
  autoExpandOnLoad,
  onOpenActivitySettings,
}: S2StrategyViewProps) {
  // FIX: Use store values with prop fallback for reactivity
  const tripInputs = useTripInputsWithFallback(propTripInputs);

  const { strategy_sections: rawStrategySections = [], open_decisions = [] } = viewModel;

  // Filter out domain specialists with no content (e.g., skiing in tropical destinations)
  // General/local_expert always show; domain specialists need content_added to be visible
  const strategy_sections = rawStrategySections.filter((section) => {
    const isGeneralType = ['general', 'local_expert'].includes(section.specialist_type || '');
    if (isGeneralType) return true;
    return section.content_added && section.content_added.length > 0;
  });

  // Use viewModel's executed_strategy_topics if not provided via props
  const resolvedExecutedTopics = executedTopics ?? viewModel.executed_strategy_topics ?? [];

  // Check if dates are set
  const hasDates = Boolean(tripInputs?.start_date && tripInputs?.end_date);

  // Compute variant from density
  // 'full' density (Plan Mode with tiles) = compact cards (Trip DNA Bar)
  // 'bridge' (PLAN mode, no tiles yet) = accordion cards (auto-expand 3s preview)
  // 'ghost' (SETUP mode with specialist content) = accordion cards (collapsed by default)
  // Both bridge and ghost use accordion - difference is auto-expand behavior
  const variant = density === 'full' ? 'compact' : (density === 'bridge' || density === 'ghost') ? 'accordion' : 'hero';

  // Determine auto-expand behavior based on density if not explicitly set
  // SETUP (ghost): Cards stay collapsed - user must expand
  // PLAN (bridge): Cards auto-expand briefly (3s) then collapse
  const shouldAutoExpand = autoExpandOnLoad ?? (density === 'bridge');

  // Use Magazine-style rendering when density is provided (new architecture)
  // Fall back to StrategyStack for backward compatibility
  const useMagazineStyle = density !== undefined;

  // =========================================================================
  // ACCORDION STATE MANAGEMENT (for Bridge Mode)
  // All hooks MUST be called unconditionally before any early return
  // =========================================================================

  // Track which cards are expanded (by section ID)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Track if this is the first render (for auto-expand preview)
  const [hasShownPreview, setHasShownPreview] = useState(false);

  // Count expanded cards
  const expandedCount = expandedIds.size;

  // Staggered auto-expand on first load - only for PLAN mode (bridge density)
  // SETUP mode (ghost density) keeps cards collapsed by default
  // Animation sequence: Each card expands for 2.5s, then collapses, with 500ms delay before next
  useEffect(() => {
    if (variant === 'accordion' && strategy_sections.length > 0 && !hasShownPreview && shouldAutoExpand) {
      setHasShownPreview(true);

      // Staggered animation timing constants
      const EXPAND_DURATION = 2500; // How long each card stays expanded
      const STAGGER_DELAY = 500;    // Delay between collapse and next expand
      const CARD_CYCLE = EXPAND_DURATION + STAGGER_DELAY; // Total time per card

      // Timeout IDs for cleanup
      const timeoutIds: NodeJS.Timeout[] = [];

      // Stagger expand each card sequentially
      strategy_sections.forEach((section, index) => {
        // When to expand this card
        const expandAt = index * CARD_CYCLE;
        // When to collapse this card
        const collapseAt = expandAt + EXPAND_DURATION;

        // Schedule expand
        const expandTimer = setTimeout(() => {
          setExpandedIds(prev => {
            const next = new Set(prev);
            next.add(section.id);
            return next;
          });
        }, expandAt);
        timeoutIds.push(expandTimer);

        // Schedule collapse
        const collapseTimer = setTimeout(() => {
          setExpandedIds(prev => {
            const next = new Set(prev);
            next.delete(section.id);
            return next;
          });
        }, collapseAt);
        timeoutIds.push(collapseTimer);
      });

      return () => {
        timeoutIds.forEach(id => clearTimeout(id));
      };
    }
  }, [variant, strategy_sections, hasShownPreview, shouldAutoExpand]);

  // Chat-triggered expansion: expand a specific specialist card
  useEffect(() => {
    let scrollTimer: ReturnType<typeof setTimeout> | null = null;

    if (expandSpecialistType && variant === 'accordion') {
      // Find the section with this specialist type
      const section = strategy_sections.find(s => s.specialist_type === expandSpecialistType);
      if (section) {
        // Expand this card
        setExpandedIds(prev => {
          const next = new Set(prev);
          next.add(section.id);
          return next;
        });

        // Scroll to the card (smooth scroll)
        scrollTimer = setTimeout(() => {
          const card = document.querySelector(`[data-specialist="${expandSpecialistType}"]`);
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 100);
      }
    }

    return () => {
      if (scrollTimer) {
        clearTimeout(scrollTimer);
      }
    };
  }, [expandSpecialistType, variant, strategy_sections]);

  // Handle expansion change for a single card
  const handleExpandChange = useCallback((sectionId: string, expanded: boolean) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (expanded) {
        next.add(sectionId);
      } else {
        next.delete(sectionId);
      }
      return next;
    });
  }, []);

  // Collapse all cards
  const handleCollapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  // Empty state - parent (StrategyStageRenderer) handles the empty case
  // This prevents duplicate skeletons and allows Bridge Mode to work correctly
  // @see docs/ux_unified_architecture.md - Grand Unification
  // NOTE: This early return MUST come AFTER all hooks
  if (strategy_sections.length === 0 && pendingTopics.length === 0) {
    return null;
  }

  return (
    <div className={cn('flex flex-col', useMagazineStyle ? 'gap-2' : 'p-[clamp(8px,1vw,16px)] space-y-[clamp(8px,1vw,16px)]')}>
      {useMagazineStyle ? (
        <>
          {/* Collapse All button (shown when 2+ accordion cards are expanded) */}
          {variant === 'accordion' && expandedCount >= 2 && (
            <div className="flex justify-end mb-1">
              <button
                onClick={handleCollapseAll}
                className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md',
                  `${DS.textSize.micro} font-bold uppercase tracking-wider`,
                  'text-zinc-500 hover:text-zinc-900',
                  'dark:text-zinc-400 dark:hover:text-white',
                  'bg-zinc-100 hover:bg-zinc-200',
                  'dark:bg-white/5 dark:hover:bg-white/10',
                  'transition-colors duration-150'
                )}
              >
                <ChevronUp className="w-3 h-3" />
                Collapse All
              </button>
            </div>
          )}

          {/* Magazine Style: StrategyHero cards */}
          {/* Note: StrategyHero is self-contained - compact mode manages its own BottomSheet */}
          {/* Accordion mode: parent manages expansion state */}
          {strategy_sections.map((section) => (
            <StrategyHero
              key={section.id}
              section={section}
              variant={variant}
              isExpanded={variant === 'accordion' ? expandedIds.has(section.id) : undefined}
              onExpandChange={variant === 'accordion' ? (expanded) => handleExpandChange(section.id, expanded) : undefined}
            />
          ))}

          {/* Pending topics placeholder */}
          {pendingTopics.map((topic) => {
            const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
            const TopicIcon = config.icon;
            return (
              <div
                key={`pending-${topic}`}
                className="flex items-center gap-3 p-3 rounded-xl bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 animate-pulse"
              >
                <div className="w-10 h-10 rounded-lg bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center">
                  <TopicIcon className="w-4 h-4 text-zinc-400" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-zinc-500">{config.label}</span>
                    <span className={`${DS.textSize.micro} px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 font-medium`}>
                      Loading...
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-0.5">Generating strategy...</p>
                </div>
              </div>
            );
          })}
        </>
      ) : (
        <>
          {/* Legacy: Strategy stack - TripHealthBar (General) + Specialist cards */}
          <StrategyStack
            sections={strategy_sections}
            pendingTopics={pendingTopics}
            executedTopics={resolvedExecutedTopics}
            tiles={tiles}
            hasDates={hasDates}
            onOpenActivitySettings={onOpenActivitySettings}
          />
        </>
      )}

      {/* Open decisions panel */}
      <OpenDecisionsPanel decisions={open_decisions} />

      {/* Secondary action - refine assumptions (optional) */}
      {onRefineAssumptions && (
        <button
          onClick={onRefineAssumptions}
          className="w-full py-2 px-4 rounded-lg text-sm text-muted-foreground hover:text-card-foreground hover:bg-muted transition-colors"
        >
          Refine assumptions
        </button>
      )}
    </div>
  );
}

export default S2StrategyView;

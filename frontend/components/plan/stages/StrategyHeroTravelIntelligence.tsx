'use client';
/**
 * StrategyHeroTravelIntelligence
 *
 * 12-category collapsible Travel Intelligence panel for the Local Expert
 * strategy section. Rendered inside the BottomSheet content.
 */

import { ChevronDown } from 'lucide-react';
import { useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { TravelIntelligence } from '@/types/plan-envelope';

import {
  renderConnectivity,
  renderCulturalNorms,
  renderMoneyCosts,
  renderSafetyHealth,
  renderTransportation,
  renderVisaEntry,
  type SectionDataHelpers,
} from './StrategyHeroTISectionsA';
import {
  renderAccommodation,
  renderNeighborhoods,
  renderPacking,
  renderScamsTraps,
  renderSeasonality,
  renderThingsToDo,
} from './StrategyHeroTISectionsB';

// =============================================================================
// TravelIntelligenceContent — dispatches to section renderer functions
// =============================================================================

interface TravelIntelligenceContentProps {
  sectionKey: string;
  data: unknown;
}

export function TravelIntelligenceContent({ sectionKey, data }: TravelIntelligenceContentProps) {
  if (!data) return null;

  const d = data as Record<string, unknown>;
  const h: SectionDataHelpers = {
    str: (key) => { const v = d[key]; return typeof v === 'string' ? v : typeof v === 'number' ? String(v) : ''; },
    num: (key) => { const v = d[key]; return typeof v === 'number' ? v : undefined; },
    bool: (key) => { const v = d[key]; return typeof v === 'boolean' ? v : undefined; },
    arr: (key) => { const v = d[key]; return Array.isArray(v) ? v : []; },
    obj: (key) => { const v = d[key]; return typeof v === 'object' && v !== null && !Array.isArray(v) ? v as Record<string, unknown> : {}; },
  };

  switch (sectionKey) {
    case 'visa_entry':        return renderVisaEntry(h);
    case 'safety_health':     return renderSafetyHealth(h);
    case 'money_costs':       return renderMoneyCosts(h);
    case 'transportation':    return renderTransportation(h);
    case 'cultural_norms':    return renderCulturalNorms(h);
    case 'connectivity':      return renderConnectivity(h);
    case 'seasonality':       return renderSeasonality(h);
    case 'things_to_do':      return renderThingsToDo(h);
    case 'neighborhoods':     return renderNeighborhoods(h);
    case 'accommodation':     return renderAccommodation(h);
    case 'scams_traps':       return renderScamsTraps(h);
    case 'packing':           return renderPacking(h);
    default:                  return null;
  }
}

// =============================================================================
// TravelIntelligencePanel — collapsible accordion panel
// =============================================================================

interface TravelIntelligencePanelProps {
  intelligence: TravelIntelligence;
}

export function TravelIntelligencePanel({ intelligence }: TravelIntelligencePanelProps) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  const sections = useMemo(() => [
    { key: 'visa_entry',     label: 'Visa & Entry',      icon: '🛂', data: intelligence.visa_entry },
    { key: 'safety_health',  label: 'Safety & Health',   icon: '🏥', data: intelligence.safety_health },
    { key: 'money_costs',    label: 'Money & Costs',     icon: '💰', data: intelligence.money_costs },
    { key: 'transportation', label: 'Getting Around',    icon: '🚕', data: intelligence.transportation },
    { key: 'cultural_norms', label: 'Cultural Norms',    icon: '🙏', data: intelligence.cultural_norms },
    { key: 'connectivity',   label: 'Connectivity',      icon: '📱', data: intelligence.connectivity },
    { key: 'seasonality',    label: 'Weather & Seasons', icon: '🌦️', data: intelligence.seasonality },
    { key: 'things_to_do',   label: 'Things to Do',      icon: '🎯', data: intelligence.things_to_do },
    { key: 'neighborhoods',  label: 'Neighborhoods',     icon: '🏘️', data: intelligence.neighborhoods },
    { key: 'accommodation',  label: 'Where to Stay',     icon: '🏨', data: intelligence.accommodation },
    { key: 'scams_traps',    label: 'Scams & Traps',     icon: '⚠️', data: intelligence.scams_traps },
    { key: 'packing',        label: 'Packing Tips',      icon: '🎒', data: intelligence.packing },
  ].filter(s => s.data && Object.keys(s.data).some(k => {
    const val = (s.data as Record<string, unknown>)[k];
    return val !== undefined && val !== null && val !== '' &&
           !(Array.isArray(val) && val.length === 0);
  })), [intelligence]);

  if (sections.length === 0) return null;

  return (
    <div className="space-y-2">
      <h4 className={DS.text.label}>Travel Intelligence</h4>
      <div className="space-y-1.5">
        {sections.map(({ key, label, icon, data }) => (
          <div
            key={key}
            className={cn(
              'rounded-lg border overflow-hidden transition-all',
              'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700'
            )}
          >
            <button
              type="button"
              onClick={() => toggleSection(key)}
              className={cn(
                'w-full flex items-center justify-between p-3 text-left',
                'hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors'
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-base">{icon}</span>
                <span className="text-sm font-medium text-zinc-900 dark:text-white">{label}</span>
              </div>
              <ChevronDown
                className={cn(
                  'w-4 h-4 text-zinc-400 transition-transform duration-200',
                  expandedSection === key && 'rotate-180'
                )}
              />
            </button>
            {expandedSection === key && (
              <div className="px-3 pb-3 pt-0 text-sm text-zinc-600 dark:text-zinc-400 space-y-2 border-t border-zinc-100 dark:border-zinc-800">
                <TravelIntelligenceContent sectionKey={key} data={data} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

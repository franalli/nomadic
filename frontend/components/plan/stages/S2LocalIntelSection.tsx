'use client';
/**
 * S2LocalIntelSection — 2-Column "War Room" layout for the Local Expert strategy card.
 * Left: Logistics & Survival. Right: Booking Radar.
 */

import { Briefcase, Building, CreditCard, Globe, Lightbulb, Plug, Sparkles, Thermometer, Ticket, Train, Wallet, Wifi } from 'lucide-react';
import React from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

type BadgeType = 'logistics' | 'essential' | 'sells_out' | 'attraction';

const BADGE_STYLES: Record<BadgeType, string> = {
  logistics: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  essential: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  sells_out: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
  attraction: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
};

interface IntelCardProps {
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  title: string;
  badge: { type: BadgeType; label: string };
  description: string;
  leadTimePrefix?: string;
  isHighPriority?: boolean;
}

function IntelCard({ icon: Icon, iconColor, title, badge, description, leadTimePrefix, isHighPriority }: IntelCardProps) {
  return (
    <div className={cn('p-3 rounded-xl border transition-colors', isHighPriority
      ? 'border-red-200 bg-red-50 dark:border-red-800/40 dark:bg-red-900/10'
      : 'border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900')}>
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
          <Icon className={cn('w-4 h-4', iconColor)} />
          <span className="font-bold text-zinc-900 dark:text-zinc-100 text-sm">{title}</span>
        </div>
        <span className={cn(`${DS.textSize.micro} font-bold px-2 py-0.5 rounded uppercase tracking-wide`, BADGE_STYLES[badge.type])}>
          {badge.label}
        </span>
      </div>
      <p className={cn('text-xs leading-relaxed', isHighPriority ? 'text-zinc-600 dark:text-zinc-300' : 'text-zinc-500 dark:text-zinc-400')}>
        {leadTimePrefix && <><strong>Action:</strong> Book {leadTimePrefix}. </>}{description}
      </p>
    </div>
  );
}

type ContentItem = { title: string; type?: string };

function getLogisticsIcon(item: ContentItem) {
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

function getAttractionIcon(item: ContentItem) {
  const text = `${item.title} ${item.type || ''}`.toLowerCase();
  if (text.includes('museum')) return { icon: Building, color: 'text-purple-500' };
  if (text.includes('restaurant') || text.includes('food')) return { icon: Sparkles, color: 'text-purple-500' };
  return { icon: Ticket, color: 'text-red-500' };
}

const LOGISTICS_TYPES = ['transport', 'logistics', 'metro', 'connectivity', 'sim', 'wifi', 'payment', 'currency', 'plug', 'power', 'visa'];
const ATTRACTION_TYPES = ['attraction', 'activity', 'experience', 'museum', 'landmark', 'restaurant'];
const FALLBACK_ICONS = [Globe, Thermometer, Plug, Wallet];
const FALLBACK_TITLES = ['Visa', 'Weather', 'Power', 'Currency'];

function extractLogisticsItems(section: StrategySection) {
  return section.content_added?.filter((c) =>
    LOGISTICS_TYPES.some((t) => c.type?.toLowerCase().includes(t) || c.title?.toLowerCase().includes(t))
  ) ?? [];
}

function extractAttractionItems(section: StrategySection) {
  return section.content_added?.filter((c) =>
    ATTRACTION_TYPES.some((t) => c.type?.toLowerCase().includes(t)) || c.logic_hook?.includes('BOOK')
  ) ?? [];
}

export function LocalIntelSection({ section }: { section: StrategySection }) {
  const logisticsItems = extractLogisticsItems(section);
  const attractionItems = extractAttractionItems(section);
  const hasLogisticsNotes = section.logistics_notes && section.logistics_notes.length > 0;
  if (logisticsItems.length === 0 && attractionItems.length === 0 && !hasLogisticsNotes) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Briefcase className="w-5 h-5 text-emerald-500" />
        <h3 className="text-base font-bold text-zinc-900 dark:text-white">Trip Operations Center</h3>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest mb-2">Logistics &amp; Survival</h4>
          {logisticsItems.slice(0, 4).map((item, idx) => {
            const { icon, color } = getLogisticsIcon(item);
            const isEssential = item.logic_hook?.toLowerCase().includes('essential');
            return <IntelCard key={`logistics-${idx}`} icon={icon} iconColor={color} title={item.title}
              badge={{ type: isEssential ? 'essential' : 'logistics', label: isEssential ? 'ESSENTIAL' : 'LOGISTICS' }}
              description={item.description || ''} />;
          })}
          {logisticsItems.length === 0 && hasLogisticsNotes && section.logistics_notes?.slice(0, 4).map((note, idx) => (
            <IntelCard key={`note-${idx}`} icon={FALLBACK_ICONS[idx % FALLBACK_ICONS.length]} iconColor="text-blue-500"
              title={FALLBACK_TITLES[idx % FALLBACK_TITLES.length]}
              badge={{ type: 'logistics', label: 'LOGISTICS' }} description={note} />
          ))}
        </div>
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest mb-2">Booking Radar</h4>
          {attractionItems.slice(0, 4).map((item, idx) => {
            const sellsOut = item.logic_hook?.toLowerCase().includes('sells out') || item.logic_hook?.includes('BOOK');
            const { icon, color } = sellsOut ? { icon: Ticket, color: 'text-red-500' } : getAttractionIcon(item);
            const leadTimeMatch = item.logic_hook?.match(/(\d+\s*(?:days?|weeks?|hours?)\s*(?:ahead|prior)?)/i);
            const leadTime = leadTimeMatch?.[1];
            const description = item.description || '';
            return <IntelCard key={`attraction-${idx}`} icon={icon} iconColor={color} title={item.title}
              badge={{ type: sellsOut ? 'sells_out' : 'attraction', label: sellsOut ? 'SELLS OUT' : 'ATTRACTION' }}
              description={description} leadTimePrefix={leadTime && sellsOut ? leadTime : undefined} isHighPriority={sellsOut} />;
          })}
          {attractionItems.length === 0 && (
            <div className="p-4 rounded-xl border border-dashed border-zinc-200 dark:border-white/10 text-center">
              <p className="text-xs text-zinc-400 dark:text-zinc-500">No advance booking items detected</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

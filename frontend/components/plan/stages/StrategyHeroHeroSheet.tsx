'use client';
/**
 * StrategyHeroHeroSheet
 *
 * BottomSheet body for StrategyHero hero mode.
 * Two layout branches: general/local_expert and activity specialist.
 */

import { Sparkles } from 'lucide-react';
import Image from 'next/image';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import { TravelIntelligencePanel } from './StrategyHeroTravelIntelligence';
import { formatConstraintRule, getConstraintIcon, getTopicLabel, renderTopicIcon } from './StrategyHeroUtils';

interface HeroSheetContentProps {
  section: StrategySection;
  constraints: NonNullable<StrategySection['constraints_applied']>;
  heroImage: string;
}

export function HeroSheetContent({ section, constraints, heroImage }: HeroSheetContentProps) {
  const topic = section.specialist_type || 'general';
  const topicLabel = getTopicLabel(topic);

  if (section.specialist_type === 'general' || section.specialist_type === 'local_expert') {
    return (
      <>
        {section.trip_summary && (
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'Destination', value: section.trip_summary.destination },
              { label: 'Dates', value: section.trip_summary.dates },
              { label: 'Travelers', value: section.trip_summary.travelers },
            ].map(({ label, value }) => (
              <div key={label} className="p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800/50">
                <span className={`${DS.textSize.micro} uppercase tracking-widest text-zinc-500 dark:text-zinc-400`}>{label}</span>
                <p className="text-sm font-medium text-zinc-900 dark:text-white mt-0.5">{value}</p>
              </div>
            ))}
          </div>
        )}
        {section.destination_gallery && section.destination_gallery.length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Destination Vibes</h4>
            <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 pb-2">
              {section.destination_gallery.filter(img => img.image_url).map((img, idx) => (
                <div key={idx} className="relative w-32 h-24 rounded-lg overflow-hidden shrink-0">
                  <Image src={img.image_url} alt={img.label || 'Destination image'} fill className="object-cover" sizes="128px" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                  <span className={`absolute bottom-2 left-2 ${DS.textSize.micro} font-medium text-white`}>{img.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {section.one_liner && <p className="text-sm italic text-zinc-500 dark:text-zinc-400">{section.one_liner}</p>}
        {section.principles && section.principles.length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Key Highlights</h4>
            <div className="space-y-2">
              {section.principles.map((p, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Sparkles className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                  <span className="text-sm text-zinc-700 dark:text-zinc-300">{p}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {section.content_added && section.content_added.length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Local Tips</h4>
            <div className="space-y-2">
              {section.content_added.map((item, idx) => (
                <div key={idx} className={DS.infoBox.container}>
                  <div className="flex gap-2">
                    {item.image_url && (
                      <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
                        <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{item.title}</p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-2">{item.description}</p>
                      {item.logic_hook && <p className={`${DS.textSize.micro} text-emerald-600 dark:text-emerald-400 mt-1 font-medium`}>💡 {item.logic_hook}</p>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {section.specialist_type === 'local_expert' && section.travel_intelligence && (
          <TravelIntelligencePanel intelligence={section.travel_intelligence} />
        )}
      </>
    );
  }

  // Activity Specialist layout
  return (
    <>
      <div className="relative h-48 w-full rounded-xl overflow-hidden">
        <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="100vw" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
        <div className="absolute bottom-3 left-3">
          <span className={cn(`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`, 'bg-white/20 backdrop-blur-md text-white border border-white/20')}>
            {renderTopicIcon(topic, 'w-3 h-3')}{topicLabel}
          </span>
        </div>
      </div>
      {section.one_liner && <div className="space-y-2"><h4 className={DS.text.label}>Strategy Logic</h4><p className={DS.text.body}>{section.one_liner}</p></div>}
      {constraints.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Applied Constraints</h4>
          <div className="space-y-2">{constraints.map((c, i) => (
            <div key={i} className={DS.infoBox.container}><div className="flex gap-2">{getConstraintIcon(c.type)}<div className="flex-1 min-w-0"><p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{formatConstraintRule(c.rule)}</p>{c.reason && <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{c.reason}</p>}</div></div></div>
          ))}</div>
        </div>
      )}
      {section.principles && section.principles.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Key Principles</h4>
          <div className="space-y-2">{section.principles.map((p, i) => (
            <div key={i} className="flex items-start gap-2"><Sparkles className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" /><span className="text-sm text-zinc-700 dark:text-zinc-300">{p}</span></div>
          ))}</div>
        </div>
      )}
      {section.content_added && section.content_added.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Expert Recommendations</h4>
          <div className="space-y-2">{section.content_added.map((item, idx) => (
            <div key={idx} className={DS.infoBox.container}><div className="flex gap-2">
              {item.image_url && <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0"><Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" /></div>}
              <div className="flex-1 min-w-0"><p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{item.title}</p><p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-2">{item.description}</p>{item.logic_hook && <p className={`${DS.textSize.micro} text-emerald-600 dark:text-emerald-400 mt-1 font-medium`}>💡 {item.logic_hook}</p>}</div>
            </div></div>
          ))}</div>
        </div>
      )}
    </>
  );
}

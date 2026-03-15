'use client';
/** StrategyHeroCompactSheet — BottomSheet body for compact mode. Three layout branches. */

import { Calendar, CheckCircle2, MapPin, Users } from 'lucide-react';
import Image from 'next/image';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import { TravelIntelligencePanel } from './StrategyHeroTravelIntelligence';
import { formatConstraintRule, getConstraintIcon, getTopicLabel, renderTopicIcon } from './StrategyHeroUtils';

// Shared recommendation list used across layout branches
export function RecommendationList({
  items,
  headingLabel,
}: {
  items: NonNullable<StrategySection['content_added']>;
  headingLabel: string;
}) {
  return (
    <div className="space-y-4">
      <h4 className={DS.text.label}>{headingLabel}</h4>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className={cn('rounded-xl border p-3 flex gap-2', 'bg-white border-zinc-200 dark:bg-zinc-900 dark:border-zinc-700')}>
            {item.image_url && (
              <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0 bg-zinc-100 dark:bg-zinc-800">
                <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-bold text-zinc-900 dark:text-white">{item.title}</p>
                {item.type && <span className={`${DS.textSize.micro} font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 px-2 py-0.5 rounded uppercase shrink-0`}>{item.type}</span>}
              </div>
              {item.description && <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed mt-1 line-clamp-2">{item.description}</p>}
              {item.logic_hook && <p className={`${DS.textSize.mini} mt-2 text-emerald-700 dark:text-emerald-300 font-medium`}>✦ {item.logic_hook}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CompactSheetContentProps {
  section: StrategySection;
  constraints: NonNullable<StrategySection['constraints_applied']>;
}

export function CompactSheetContent({ section, constraints }: CompactSheetContentProps) {
  if (section.specialist_type === 'general') {
    return (
      <>
        {section.trip_summary && (
          <div className="grid grid-cols-3 gap-2">
            {[
              { Icon: MapPin, label: 'Dest', value: section.trip_summary.destination },
              { Icon: Calendar, label: 'Dates', value: section.trip_summary.dates },
              { Icon: Users, label: 'Travelers', value: section.trip_summary.travelers },
            ].map(({ Icon, label, value }) => (
              <div key={label} className={cn(DS.infoBox.container, 'p-3 flex flex-col items-center text-center')}>
                <Icon className="w-4 h-4 text-emerald-500 mb-1" />
                <span className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400 font-bold`}>{label}</span>
                <span className="text-xs font-medium text-zinc-900 dark:text-white">{value}</span>
              </div>
            ))}
          </div>
        )}
        {section.vibe_trio && section.vibe_trio.filter(v => v.image_url).length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Trip Vibe</h4>
            <div className="grid grid-cols-2 gap-2 aspect-[16/9] rounded-2xl overflow-hidden">
              {section.vibe_trio[0]?.image_url && (
                <div className="relative h-full">
                  <Image src={section.vibe_trio[0].image_url} alt={section.vibe_trio[0].label || 'Trip vibe'} fill className="object-cover" sizes="300px" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent flex items-end p-3">
                    <span className="text-white text-xs font-bold uppercase tracking-wider drop-shadow-md">{section.vibe_trio[0].label}</span>
                  </div>
                </div>
              )}
              <div className="grid grid-rows-2 gap-2 h-full">
                {section.vibe_trio.slice(1, 3).filter(v => v.image_url).map((vibe, i) => (
                  <div key={i} className="relative h-full">
                    <Image src={vibe.image_url} alt={vibe.label || 'Trip vibe'} fill className="object-cover" sizes="200px" />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent flex items-end p-3">
                      <span className={`text-white ${DS.textSize.micro} font-bold uppercase tracking-wider drop-shadow-md`}>{vibe.label}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
        {(!section.vibe_trio || section.vibe_trio.length === 0) && section.content_added && section.content_added.filter(c => c.image_url).length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Destination Vibe</h4>
            <div className="grid grid-cols-2 gap-2">
              {section.content_added.filter(item => item.image_url).slice(0, 4).map((item, i) => (
                <div key={i} className="relative aspect-square rounded-xl overflow-hidden bg-zinc-100 dark:bg-zinc-900">
                  <Image src={item.image_url!} alt={item.title} fill className="object-cover" sizes="200px" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                  <span className="absolute bottom-2 left-2 text-xs font-bold text-white drop-shadow-md">{item.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {(section.editorial_one_liner || section.one_liner) && (
          <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/5">
            <p className="text-zinc-600 dark:text-zinc-300 italic text-sm leading-relaxed">&ldquo;{section.editorial_one_liner || section.one_liner}&rdquo;</p>
          </div>
        )}
        {section.principles && section.principles.length > 0 && (
          <div className="space-y-4">
            <h4 className={DS.text.label}>Trip Highlights</h4>
            <ul className="space-y-2">
              {section.principles.map((p, i) => (
                <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300">
                  <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />{p}
                </li>
              ))}
            </ul>
          </div>
        )}
      </>
    );
  }

  if (section.specialist_type === 'local_expert' && section.destination_gallery && section.destination_gallery.length > 0) {
    return (
      <>
        <div className="space-y-2">
          <h4 className={DS.text.label}>Destination Preview</h4>
          <div className="flex gap-2 overflow-x-auto pb-2 snap-x no-scrollbar -mx-4 px-4">
            {section.destination_gallery.filter(img => img.image_url).map((img, idx) => (
              <div key={idx} className="shrink-0 snap-center relative w-56 h-36 rounded-xl overflow-hidden shadow-card dark:shadow-none border border-zinc-200 dark:border-zinc-700/50">
                <Image src={img.image_url} alt={img.label || 'Destination image'} fill className="object-cover" sizes="224px" />
              </div>
            ))}
          </div>
        </div>
        {section.one_liner && <div className="space-y-2"><h4 className={DS.text.label}>Local Insight</h4><p className={DS.text.body}>{section.one_liner}</p></div>}
        {section.principles && section.principles.length > 0 && (
          <div className="space-y-4"><h4 className={DS.text.label}>Key Principles</h4>
            <ul className="space-y-2">{section.principles.map((p, i) => (
              <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />{p}</li>
            ))}</ul>
          </div>
        )}
        {section.content_added && section.content_added.length > 0 && <RecommendationList items={section.content_added} headingLabel="Local Recommendations" />}
        {section.travel_intelligence && <TravelIntelligencePanel intelligence={section.travel_intelligence} />}
      </>
    );
  }

  // Activity Specialist layout
  const topic = section.specialist_type || 'general';
  const heroImage = section.hero_image || '';
  return (
    <>
      {heroImage && (
        <div className="relative h-48 md:h-64 w-full rounded-xl overflow-hidden">
          <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="(max-width: 768px) 100vw, 600px" />
          <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
          <div className="absolute bottom-3 left-3 right-3">
            <span className={cn(`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`, 'bg-white/20 backdrop-blur-md text-white border border-white/20')}>
              {renderTopicIcon(topic, 'w-3 h-3')}{getTopicLabel(topic)}
            </span>
          </div>
        </div>
      )}
      {section.one_liner && <div className="space-y-2"><h4 className={DS.text.label}>Strategy Logic</h4><p className={DS.text.body}>{section.one_liner}</p></div>}
      {constraints.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Applied Constraints</h4>
          <div className="grid gap-2">{constraints.map((c, i) => (
            <div key={i} className={DS.infoBox.container}><div className="flex gap-2">{getConstraintIcon(c.type)}<div className="flex-1 min-w-0"><p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{formatConstraintRule(c.rule)}</p>{c.reason && <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{c.reason}</p>}</div></div></div>
          ))}</div>
        </div>
      )}
      {section.principles && section.principles.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Key Principles</h4>
          <ul className="space-y-2">{section.principles.map((p, i) => (
            <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />{p}</li>
          ))}</ul>
        </div>
      )}
      {section.content_added && section.content_added.length > 0 && <RecommendationList items={section.content_added} headingLabel="Expert Recommendations" />}
      {section.logistics_notes && section.logistics_notes.length > 0 && (
        <div className="space-y-4"><h4 className={DS.text.label}>Logistics Notes</h4>
          <ul className="space-y-1.5">{section.logistics_notes.map((note, i) => (
            <li key={i} className="text-xs text-zinc-600 dark:text-zinc-400 flex items-start gap-2"><span className="text-zinc-400 mt-0.5">•</span>{note}</li>
          ))}</ul>
        </div>
      )}
    </>
  );
}

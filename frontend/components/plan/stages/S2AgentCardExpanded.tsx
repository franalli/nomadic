'use client';
/** S2AgentCardExpanded — expanded detail panel rendered inside AgentCard when isExpanded && !infeasible. */

import { Lightbulb, ShieldCheck, Sparkles } from 'lucide-react';
import Image from 'next/image';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import { LocalIntelSection } from './S2LocalIntelSection';
import { formatConstraintTitle, RichText } from './S2TopicConfig';

export function S2AgentCardExpanded({ section }: { section: StrategySection }) {
  return (
    <div className="px-4 pb-4 pt-2 border-t border-border/50 space-y-4">
      {/* Destination Gallery — Vibe Trio for Local Expert */}
      {section.specialist_type === 'local_expert' && section.destination_gallery && section.destination_gallery.length > 0 && (
        <div className="mb-2">
          <div className="flex gap-3 overflow-x-auto pb-3 snap-x no-scrollbar md:hidden">
            {section.destination_gallery.filter(img => Boolean(img.image_url)).map((img, idx) => (
              <div key={idx} className="shrink-0 snap-center relative w-64 h-40 rounded-xl overflow-hidden shadow-card dark:shadow-none border border-zinc-200 dark:border-zinc-700/50">
                <Image src={img.image_url} alt={img.label} fill className="object-cover" />
              </div>
            ))}
          </div>
          <div className="hidden md:grid grid-cols-3 gap-4">
            {section.destination_gallery.filter(img => Boolean(img.image_url)).map((img, idx) => (
              <div key={idx} className="relative h-48 md:h-64 rounded-xl overflow-hidden shadow-card dark:shadow-none border border-zinc-100 dark:border-zinc-700/50 group">
                <Image src={img.image_url} alt={img.label} fill className="object-cover transition-transform duration-500 group-hover:scale-105" />
              </div>
            ))}
          </div>
        </div>
      )}

      {section.specialist_type === 'local_expert' && <LocalIntelSection section={section} />}

      {/* Specialist Constraints */}
      {section.constraints_applied && section.constraints_applied.length > 0 && (
        <div>
          <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 flex items-center gap-2">
            <ShieldCheck size={12} className="text-emerald-600 dark:text-emerald-400" /> Applied Constraints
          </h5>
          <div className="space-y-3">
            {section.constraints_applied.map((c, idx) => (
              <div key={idx} className="flex items-start gap-3">
                <div className="shrink-0 mt-0.5 w-5 h-5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 flex items-center justify-center">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                </div>
                <div className="space-y-0.5">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed font-medium">{formatConstraintTitle(c.rule)}</p>
                  {(c.reason || c.type) && <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">{c.reason || c.type}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expert Recommendations — skip for local_expert */}
      {section.content_added && section.content_added.length > 0 && section.specialist_type !== 'local_expert' && (
        <div>
          <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 flex items-center gap-2">
            <Lightbulb size={12} className="text-emerald-600 dark:text-emerald-400" /> Expert Recommendations
          </h5>
          <div className="grid gap-3">
            {section.content_added.map((c, idx) => (
              <div key={idx} className={cn('rounded-xl border transition-colors p-4 flex gap-3', 'bg-white border-zinc-200 hover:border-emerald-500/30 shadow-card', 'dark:bg-zinc-900 dark:border-zinc-700 dark:hover:border-zinc-600 dark:shadow-none')}>
                {c.image_url && (
                  <div className="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0 bg-zinc-100 dark:bg-zinc-900">
                    <Image src={c.image_url} alt={c.title} width={64} height={64} className="object-cover w-full h-full" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between items-start mb-1">
                    <span className="text-sm font-bold text-zinc-900 dark:text-white">{c.title}</span>
                    {c.type && <span className={`${DS.textSize.micro} font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded uppercase`}>{c.type}</span>}
                  </div>
                  {c.description && <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed line-clamp-2">{c.description}</p>}
                  {c.logic_hook && (
                    <div className={cn(`${DS.textSize.mini} mt-2.5 inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md border`, 'text-emerald-700 bg-emerald-50 border-emerald-200', `dark:text-emerald-300 dark:bg-emerald-950 dark:border-emerald-700/60 dark:${DS.glowClass.badge}`)}>
                      <Sparkles size={12} className="text-emerald-600 dark:text-emerald-400 flex-shrink-0 animate-pulse" />
                      <span className="font-medium tracking-wide">{c.logic_hook}</span>
                    </div>
                  )}
                  {c.day && <div className={`${DS.textSize.micro} text-muted-foreground mt-1.5`}>Day {c.day}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Booking artifacts — general agent only */}
      {section.booking_artifacts && section.specialist_type === 'general' && (
        <div className="flex flex-wrap gap-2 py-2 border-b border-border/30">
          <span className="text-xs text-muted-foreground">Booking surfaces:</span>
          {section.booking_artifacts.activities_count > 0 && <span className="text-xs topic-bullet font-medium">{section.booking_artifacts.activities_count} activities shortlisted</span>}
          {section.booking_artifacts.hotels_count > 0 && <span className="text-xs topic-bullet font-medium">{section.booking_artifacts.hotels_count} hotels recommended</span>}
        </div>
      )}

      {/* Optional upgrades */}
      {section.optional_upgrades && section.optional_upgrades.length > 0 && (
        <div>
          <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Optional upgrades</h5>
          <ul className="space-y-1.5">
            {section.optional_upgrades.slice(0, 3).map((item, idx) => (
              <li key={idx} className="text-xs text-muted-foreground flex items-start gap-2">
                <span className="text-muted-foreground/70 mt-0.5">+</span><RichText>{item}</RichText>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Logistics notes */}
      {section.logistics_notes && section.logistics_notes.length > 0 && (
        <div>
          <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Logistics</h5>
          <ul className="space-y-1.5">
            {section.logistics_notes.slice(0, 4).map((item, idx) => (
              <li key={idx} className="text-xs text-muted-foreground flex items-start gap-2">
                <span className="text-muted-foreground/50 mt-0.5">-</span><RichText>{item}</RichText>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Tradeoffs + Impact */}
      {section.tradeoffs_summary && (
        <div>
          <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Why this approach</h5>
          <p className="text-xs text-muted-foreground"><RichText>{section.tradeoffs_summary}</RichText></p>
        </div>
      )}
      {section.impact_areas && section.impact_areas.length > 0 && (
        <div className="flex items-center gap-2 pt-2 border-t border-border/30">
          <span className="text-xs text-muted-foreground">Impact:</span>
          {section.impact_areas.map((area, i) => <span key={i} className="text-xs px-1.5 py-0.5 topic-badge rounded">{area}</span>)}
        </div>
      )}

      {/* Provenance (debug info) */}
      {(section.strategy_node_id || section.strategy_version) && (
        <details className={`${DS.textSize.micro} text-muted-foreground/70`}>
          <summary className="cursor-pointer">ⓘ Provenance</summary>
          <p className="mt-1 pl-2">Generated by: <span className="topic-bullet">{section.strategy_node_id}</span>{section.strategy_version && ` • v${section.strategy_version}`}</p>
        </details>
      )}
    </div>
  );
}

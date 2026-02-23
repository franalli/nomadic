import { describe, expect, it } from 'vitest';

import { buildDestinationIntel } from '@/lib/travelIntel';
import type { StrategySection } from '@/types/plan-envelope';

function makeSection(
  constraints: Array<Record<string, unknown>>,
  principles: string[] = []
): StrategySection {
  return {
    id: 'strategy_local_expert',
    title: 'Travel Intel',
    specialist_type: 'local_expert',
    principles,
    constraints_applied: constraints as NonNullable<StrategySection['constraints_applied']>,
    must_dos: [],
    optional_upgrades: [],
    logistics_notes: [],
    bullets: [],
    content_added: [],
  };
}

describe('travelIntel categorization', () => {
  it('does not classify tax-free passport shopping guidance as Visa', () => {
    const line = 'Keep passport handy for tax-free forms on purchases over 154.95 EUR.';
    const sections: StrategySection[] = [
      makeSection([
        {
          type: 'visa',
          severity: 'soft',
          reason: line,
          rule: '',
        },
      ]),
    ];

    const { categories } = buildDestinationIntel(sections);
    const visa = categories.find((c) => c.key === 'visa');
    const money = categories.find((c) => c.key === 'money');

    expect(visa?.items ?? []).not.toContain(line);
    expect(money?.items ?? []).toContain(line);
  });

  it('does not bucket non-safety store-hours text under Safety even if type=safety', () => {
    const sections: StrategySection[] = [
      makeSection([
        {
          type: 'safety',
          severity: 'soft',
          reason: 'Smaller shops often close between 1:00 PM and 4:00 PM.',
          rule: '',
        },
      ]),
    ];

    const { categories } = buildDestinationIntel(sections);

    const safety = categories.find((c) => c.key === 'safety');
    const culture = categories.find((c) => c.key === 'culture');

    expect(safety?.items ?? []).not.toContain('Smaller shops often close between 1:00 PM and 4:00 PM.');
    expect((culture?.items ?? []).length).toBeGreaterThan(0);
  });

  it('keeps genuine safety text in Safety', () => {
    const sections: StrategySection[] = [
      makeSection([
        {
          type: 'safety',
          severity: 'soft',
          reason: 'Pickpockets are active near Termini and the Trevi area.',
          rule: '',
        },
      ]),
    ];

    const { categories } = buildDestinationIntel(sections);
    const safety = categories.find((c) => c.key === 'safety');

    expect(safety).toBeDefined();
    expect(safety?.items).toContain('Pickpockets are active near Termini and the Trevi area.');
  });
});

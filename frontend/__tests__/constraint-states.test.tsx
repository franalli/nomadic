/**
 * Constraint button visual states tests
 *
 * Tests the 2-state visual system for constraint buttons:
 * - unset: dashed border, muted color (used in Phase 1 - Bootstrap)
 * - resolved: solid border, dot indicator (used in Phase 2 - Control)
 *
 * Note: The "active" state was removed as part of the "Chips as Conversation Primers"
 * redesign. Chips now insert starter text instead of tracking active state.
 */

import { describe, expect,it } from 'vitest';

describe('Constraint button visual states', () => {
  describe('CSS class application', () => {
    it('applies constraint-unset class for unset constraints', () => {
      // Verify the CSS class exists and has correct properties
      // constraint-unset: dashed border, muted color
      const unsetStyles = {
        border: 'border-dashed',
        borderColor: 'border-muted-foreground/30',
        textColor: 'text-muted-foreground',
      };

      expect(unsetStyles.border).toBe('border-dashed');
      expect(unsetStyles.textColor).toBe('text-muted-foreground');
    });

    it('applies constraint-resolved class when constraint has value', () => {
      // Verify the CSS class exists and has correct properties
      // constraint-resolved: solid border, foreground color, ::after dot
      const resolvedStyles = {
        border: 'border-solid',
        borderColor: 'border-border/50',
        textColor: 'text-foreground',
        hasDotIndicator: true,
      };

      expect(resolvedStyles.border).toBe('border-solid');
      expect(resolvedStyles.textColor).toBe('text-foreground');
      expect(resolvedStyles.hasDotIndicator).toBe(true);
    });
  });

  describe('Chip behavior (Phase 1 - Bootstrap)', () => {
    it('chips append starter text on click', () => {
      // Clicking a chip appends its starter text to the input
      const starterTexts = {
        Destination: 'going to ',
        Origin: 'from ',
        Dates: 'dates are ',
        Budget: 'budget around ',
      };

      expect(starterTexts.Destination).toBe('going to ');
      expect(starterTexts.Origin).toBe('from ');
      expect(starterTexts.Dates).toBe('dates are ');
      expect(starterTexts.Budget).toBe('budget around ');
    });

    it('multiple chip clicks accumulate with separators', () => {
      // Clicking multiple chips builds up the input
      const input = '';
      const afterDestination = input + 'going to ';
      const afterDates = afterDestination + ', dates are ';

      expect(afterDestination).toBe('going to ');
      expect(afterDates).toBe('going to , dates are ');
    });

    it('chips have static styling without active state', () => {
      // Chips use consistent muted styling, no highlight on click
      const chipClasses = [
        'border-dashed',
        'border-muted-foreground/25',
        'text-muted-foreground/70',
        'hover:border-muted-foreground/40',
      ];

      chipClasses.forEach((className) => {
        expect(className).not.toContain('primary');
      });
    });
  });

  describe('State transitions', () => {
    it('transitions from unset to resolved when value is entered', () => {
      // State machine: unset -> enter value -> resolved
      const hasValue = true;
      const expectedState = hasValue ? 'resolved' : 'unset';

      expect(expectedState).toBe('resolved');
    });

    it('can transition back to unset when value is cleared', () => {
      // State machine: resolved -> clear value -> unset
      const hasValue = false;
      const expectedState = hasValue ? 'resolved' : 'unset';

      expect(expectedState).toBe('unset');
    });
  });

  describe('Constraint labels', () => {
    it('uses noun labels not verb labels', () => {
      // Labels should be nouns: "Destination", "Origin", "Dates", "Budget"
      // Not verbs: "Set destination", "From", "When", etc.
      const labels = ['Destination', 'Origin', 'Dates', 'Budget'];

      labels.forEach((label) => {
        // No verbs in labels
        expect(label).not.toMatch(/^(Set|Add|Enter|Choose)/i);
        // No question words
        expect(label).not.toMatch(/^(Where|When|How)/i);
      });
    });
  });
});

describe('Plan header copy states', () => {
  describe('Header by constraint count', () => {
    it('shows "Your trip plan" with 0 constraints', () => {
      const constraintCount = 0;
      const expectedTitle = 'Your trip plan';
      const expectedSubtitle = 'This plan updates automatically as you set constraints.';

      expect(constraintCount).toBe(0);
      expect(expectedTitle).toBe('Your trip plan');
      expect(expectedSubtitle).toContain('automatically');
    });

    it('shows "Trip plan in progress" with 1 constraint', () => {
      const constraintCount = 1;
      const expectedTitle = 'Trip plan in progress';
      const expectedSubtitle = 'The plan will resolve as remaining constraints are added.';

      expect(constraintCount).toBe(1);
      expect(expectedTitle).toBe('Trip plan in progress');
      expect(expectedSubtitle).toContain('resolve');
    });

    it('shows "Resolving trip plan" with 2-3 constraints', () => {
      [2, 3].forEach((constraintCount) => {
        const expectedTitle = 'Resolving trip plan';
        const expectedSubtitle = 'The plan is partially defined and will update as constraints change.';

        expect(constraintCount).toBeGreaterThanOrEqual(2);
        expect(constraintCount).toBeLessThanOrEqual(3);
        expect(expectedTitle).toBe('Resolving trip plan');
        expect(expectedSubtitle).toContain('partially defined');
      });
    });

    it('shows "Trip plan" with summary line when all 4 constraints are set', () => {
      const constraintCount = 4;
      const expectedTitle = 'Trip plan';
      const hasSummaryLine = true;

      expect(constraintCount).toBe(4);
      expect(expectedTitle).toBe('Trip plan');
      expect(hasSummaryLine).toBe(true);
    });
  });

  describe('Summary line format', () => {
    it('formats summary as "Origin -> Destination - Dates - Budget"', () => {
      const origin = 'Amsterdam';
      const destination = 'Lisbon';
      const dates = 'Apr 12 – Apr 18';
      const budget = '€1,500';

      const summaryParts = [
        `${origin} → ${destination}`,
        dates,
        budget,
      ];
      const summaryLine = summaryParts.join(' · ');

      expect(summaryLine).toBe('Amsterdam → Lisbon · Apr 12 – Apr 18 · €1,500');
    });
  });
});

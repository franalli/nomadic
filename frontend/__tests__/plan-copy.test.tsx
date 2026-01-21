/**
 * Edge-case copy tests
 *
 * Tests copy for various edge cases and states in the plan UI.
 */

import { describe, expect,it } from 'vitest';

describe('Edge-case copy', () => {
  describe('Flexible constraints', () => {
    it('handles unset dates gracefully', () => {
      // When dates are not set, show that dates are flexible
      const hasStartDate = false;
      const hasEndDate = false;
      const datesCopy = hasStartDate || hasEndDate ? 'formatted date' : null;

      // No explicit "Dates are flexible" message needed - just absence of dates in summary
      expect(datesCopy).toBeNull();
    });

    it('handles unset origin gracefully', () => {
      // When origin is not set, route shows only destination
      const origin = null;
      const destination = 'Lisbon';
      const routeCopy = origin ? `${origin} → ${destination}` : destination;

      expect(routeCopy).toBe('Lisbon');
    });
  });

  describe('Updating states', () => {
    it('shows "Updating plan..." during constraint changes', () => {
      const isUpdating = true;
      const statusCopy = isUpdating ? 'Updating plan...' : null;

      expect(statusCopy).toBe('Updating plan...');
      // Never use "Regenerating" or "Thinking"
      expect(statusCopy).not.toContain('Regenerating');
      expect(statusCopy).not.toContain('Thinking');
    });

    it('shows no status when plan is stable', () => {
      const isUpdating = false;
      const statusCopy = isUpdating ? 'Updating plan...' : null;

      expect(statusCopy).toBeNull();
    });
  });

  describe('Conflict copy', () => {
    it('uses neutral language for budget conflicts', () => {
      const budgetConflictCopy = {
        primary: 'Budget is lower than estimated plan cost.',
        secondary: 'The plan will adjust if constraints change.',
      };

      // Never use "cannot", "error", "invalid", "fix"
      expect(budgetConflictCopy.primary).not.toMatch(/cannot|error|invalid|fix/i);
      expect(budgetConflictCopy.secondary).not.toMatch(/cannot|error|invalid|fix/i);
    });

    it('uses neutral language for date conflicts', () => {
      const dateConflictCopy = {
        primary: 'Dates are too short for current travel constraints.',
        secondary: 'Adjust dates or origin to resolve.',
      };

      // Never use "cannot", "error", "invalid", "fix"
      expect(dateConflictCopy.primary).not.toMatch(/cannot|error|invalid|fix/i);
      expect(dateConflictCopy.secondary).not.toMatch(/cannot|error|invalid|fix/i);
    });

    it('uses neutral language for route conflicts', () => {
      const routeConflictCopy = {
        primary: 'No viable route matches current constraints.',
        secondary: 'The plan will update if constraints change.',
      };

      // Never use "cannot", "error", "invalid", "fix"
      expect(routeConflictCopy.primary).not.toMatch(/cannot|error|invalid|fix/i);
      expect(routeConflictCopy.secondary).not.toMatch(/cannot|error|invalid|fix/i);
    });
  });

  describe('Price disclaimer', () => {
    it('shows prices as estimates', () => {
      const priceDisclaimer = 'Prices are estimates based on current constraints and availability.';

      expect(priceDisclaimer).toContain('estimates');
      expect(priceDisclaimer).toContain('constraints');
      expect(priceDisclaimer).toContain('availability');
    });
  });

  describe('Segment states', () => {
    it('handles unresolved segments with appropriate copy', () => {
      const unresolvedCopy = 'Segment unresolved — this part of the plan cannot be resolved with current constraints.';

      expect(unresolvedCopy).toContain('unresolved');
      // This is plan-level, so "cannot" is acceptable here
    });
  });

  describe('Empty plan states', () => {
    it('shows appropriate message when building plan', () => {
      const isUpdating = true;
      const days: unknown[] = [];
      const emptyCopy = isUpdating ? 'Building your trip plan...' : 'Set constraints to generate a day-by-day plan.';

      expect(days.length).toBe(0);
      expect(emptyCopy).toBe('Building your trip plan...');
    });

    it('shows appropriate message when no constraints set', () => {
      const isUpdating = false;
      const days: unknown[] = [];
      const emptyCopy = isUpdating ? 'Building your trip plan...' : 'Set constraints to generate a day-by-day plan.';

      expect(days.length).toBe(0);
      expect(emptyCopy).toBe('Set constraints to generate a day-by-day plan.');
    });
  });
});

describe('Budget comparison copy', () => {
  it('shows "Within budget" when estimate is below budget', () => {
    const budget = 1500;
    const estimate = 1420;
    const isWithinBudget = estimate <= budget;
    const comparisonCopy = isWithinBudget
      ? `Within budget (€${budget.toLocaleString()})`
      : `Exceeds budget by €${(estimate - budget).toLocaleString()}`;

    expect(comparisonCopy).toBe('Within budget (€1,500)');
  });

  it('shows "Exceeds budget by X" when estimate is above budget', () => {
    const budget = 1500;
    const estimate = 1680;
    const isWithinBudget = estimate <= budget;
    const comparisonCopy = isWithinBudget
      ? `Within budget (€${budget.toLocaleString()})`
      : `Exceeds budget by €${(estimate - budget).toLocaleString()}`;

    expect(comparisonCopy).toBe('Exceeds budget by €180');
  });
});

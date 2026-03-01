import { expect, test } from "@playwright/test";

/**
 * Rome Golden Path E2E — validates the full two-turn planning flow:
 *   Turn 1: "rome" → strategy sections + suggestion chips
 *   Turn 2: "Mar 1-7" → day cards with activities
 *
 * Requires both frontend (localhost:3000) and backend (localhost:8000) running.
 */

test.describe("Rome Golden Path", () => {
  test("two-turn planning produces strategy + itinerary", async ({ page }) => {
    // ---------------------------------------------------------------
    // Navigate to landing
    // ---------------------------------------------------------------
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // ---------------------------------------------------------------
    // Turn 1: Send "rome"
    // ---------------------------------------------------------------
    const chatInput = page.getByRole("textbox", { name: /chat message/i });
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill("rome");

    const sendButton = page.getByRole("button", { name: /send/i });
    await sendButton.click();

    // Wait for streaming to complete — the "complete" SSE event triggers
    // the plan panel to render. We detect completion by waiting for the
    // destination text to appear.
    const planPanel = page.locator('[data-testid="plan-panel"]').or(
      page.locator(".plan-panel"),
    );

    // Assert: destination shows "Rome"
    await expect(
      planPanel.getByText(/rome/i).first(),
    ).toBeVisible({ timeout: 60_000 });

    // Assert: strategy section visible (local expert or specialist)
    const strategySection = page
      .locator('[data-testid="strategy-section"]')
      .or(page.locator(".strategy-section"))
      .or(page.locator('[class*="strategy"]'));
    await expect(strategySection.first()).toBeVisible({ timeout: 30_000 });

    // Assert: suggestion chips appear
    const chips = page
      .locator('[data-testid="suggestion-chip"]')
      .or(page.locator('[class*="suggestion"]').or(page.locator("button").filter({ hasText: /mar|date|when/i })));
    await expect(chips.first()).toBeVisible({ timeout: 30_000 });

    // ---------------------------------------------------------------
    // Turn 2: Send dates "Mar 1-7"
    // ---------------------------------------------------------------
    await chatInput.fill("Mar 1-7");
    await sendButton.click();

    // Wait for itinerary to build — day cards should appear
    const dayCards = page
      .locator('[data-testid="day-card"]')
      .or(page.locator('[class*="day-card"]'))
      .or(page.locator('[class*="DayCard"]'));

    // Assert: at least 6 day cards (7-day trip)
    await expect(dayCards.first()).toBeVisible({ timeout: 90_000 });
    const dayCardCount = await dayCards.count();
    expect(dayCardCount).toBeGreaterThanOrEqual(6);

    // Assert: Day 1 has "Arrival" label
    const firstDayCard = dayCards.first();
    await expect(
      firstDayCard.getByText(/arrival/i),
    ).toBeVisible({ timeout: 10_000 });

    // Assert: Last day has "Departure" label
    const lastDayCard = dayCards.last();
    await expect(
      lastDayCard.getByText(/departure/i),
    ).toBeVisible({ timeout: 10_000 });

    // Assert: at least one interior day has an activity block
    const activityBlocks = page
      .locator('[data-testid="activity-block"]')
      .or(page.locator('[class*="activity-block"]'))
      .or(page.locator('[class*="ActivityBlock"]'));
    const activityCount = await activityBlocks.count();
    expect(activityCount).toBeGreaterThanOrEqual(1);

    // Assert: hotel tiles visible
    const hotelTiles = page
      .locator('[data-testid="hotel-tile"]')
      .or(page.locator('[class*="hotel"]').filter({ hasText: /hotel|accommodation/i }));
    await expect(hotelTiles.first()).toBeVisible({ timeout: 15_000 });

    // Screenshot for visual baseline
    await page.screenshot({
      path: "e2e/screenshots/rome-golden-path.png",
      fullPage: true,
    });
  });
});

/**
 * Hybrid Q&A E2E Tests
 *
 * Tests for messages that contain BOTH a workflow action AND a Q&A question.
 * The system must:
 * 1. Process the workflow action (confirmation, detour, shortcut)
 * 2. ALSO respond to the Q&A question
 * 3. NEVER let the Q&A modify workflow state
 *
 * Key principle: Q&A is informational only - it reads but never writes.
 *
 * Run these tests:
 *   cd atelier-ai-frontend && npm run test:e2e
 *
 * Prerequisites:
 *   - Backend running on http://localhost:8000
 *   - Frontend running on http://localhost:3000
 */

import { test, expect, Page } from '@playwright/test';

// Helper: Generate unique test email
function testEmail(): string {
  const timestamp = Date.now();
  return `playwright-${timestamp}@test.example.com`;
}

// Helper: Send a message in the chat UI
async function sendMessage(page: Page, message: string): Promise<void> {
  // Wait for textarea to be enabled
  const textarea = page.getByRole('textbox');
  await textarea.waitFor({ state: 'visible' });

  // Fill the message
  await textarea.fill(message);

  // Click send button
  const sendButton = page.getByRole('button', { name: 'Send' });
  await sendButton.click();
}

// Helper: Wait for assistant response
async function waitForResponse(page: Page, timeout = 60000): Promise<string> {
  // Wait for "Shami is typing..." to appear and disappear
  try {
    await page.getByText('Shami is typing...').waitFor({ state: 'visible', timeout: 10000 });
    await page.getByText('Shami is typing...').waitFor({ state: 'hidden', timeout });
  } catch {
    // Typing indicator might not appear or already gone
  }

  // Wait for response content to appear
  await page.waitForTimeout(2000);

  // Get all paragraphs from the chat - the response should contain structured content
  const content = await page.locator('.prose, [class*="markdown"], p').allTextContents();
  return content.join('\n');
}

// =============================================================================
// TEST SUITE: Confirmation + Q&A (Most Important Case)
// =============================================================================

test.describe('Hybrid Q&A: Confirmation + General Q&A', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('room confirmation with parking Q&A should respond to both', async ({ page }) => {
    /**
     * Scenario: User confirms room AND asks about parking in same message
     * Expected: Response acknowledges room confirmation AND provides parking info
     */
    const email = testEmail();

    // Step 1: Start with initial inquiry
    const inquiry = `Subject: Private Dinner Inquiry
From: ${email}

Hi, I'd like to book a private dinner for 20 guests on March 15, 2026.
We need a room with a nice ambiance for an anniversary celebration.

Best regards,
Test User`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Verify we got room availability (not manual review fallback)
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Verify NO catering section appears for dinner event type
    const cateringSection = page.getByText('Menu Options');
    await expect(cateringSection).not.toBeVisible();

    // Step 2: Send hybrid message - confirm room + ask about parking
    const hybridMessage = 'Room B sounds perfect, I will take it. What parking options do you have?';
    await sendMessage(page, hybridMessage);
    await waitForResponse(page);

    // Verify BOTH intents are addressed:
    // 1. Room B is shown/acknowledged
    await expect(page.getByText('Room B').first()).toBeVisible({ timeout: 30000 });

    // 2. Parking question answered
    await expect(page.getByText('Parking Information')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/parking|garage|Europaallee/i)).toBeVisible();

    // 3. HIL task created for offer
    await expect(page.getByText('Manager Tasks')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('offer message')).toBeVisible();
  });

  test('room confirmation with catering Q&A should respond to both', async ({ page }) => {
    /**
     * Scenario: User confirms room AND asks about catering options
     */
    const email = testEmail();

    const inquiry = `Subject: Corporate Meeting
From: ${email}

Hello, we need a meeting room for 15 people on April 10, 2026.
Duration: 9am to 5pm. Standard conference setup please.

Thanks,
Test Corp`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Should get room availability
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Hybrid: confirm room + ask catering explicitly
    const hybridMessage = "Let's proceed with Room C. What catering options do you have?";
    await sendMessage(page, hybridMessage);
    await waitForResponse(page);

    // Should address both
    await expect(page.getByText('Room C').first()).toBeVisible({ timeout: 30000 });
    // Catering should only appear when explicitly asked
    await expect(page.getByText(/catering|menu|food/i)).toBeVisible({ timeout: 10000 });
  });
});

// =============================================================================
// TEST SUITE: February Availability (BUG-010 Regression)
// =============================================================================

test.describe('Hybrid Q&A: Month-Constrained Availability', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('room confirmation with February next year availability Q&A', async ({ page }) => {
    /**
     * This is the original BUG-010 scenario:
     * User confirms room AND asks about February next year availability
     * Expected: Response confirms room AND provides February 2027 dates
     */
    const email = testEmail();

    const inquiry = `Subject: Birthday Party
From: ${email}

Hi, planning a birthday party for 30 guests on June 1, 2026.
Evening event, buffet style setup preferred.

Thanks!`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Verify room availability shown
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Hybrid: confirm room + ask about February NEXT YEAR
    const hybridMessage =
      "Room B looks great, let's proceed with that. " +
      "By the way, which rooms would be available for a larger event in February next year?";

    await sendMessage(page, hybridMessage);
    await waitForResponse(page);

    // Should address Room B
    await expect(page.getByText('Room B').first()).toBeVisible({ timeout: 30000 });

    // Should show February info with 2027 dates
    await expect(page.getByText(/February|feb/i)).toBeVisible({ timeout: 10000 });
    // The dates should be 2027 (next year)
    await expect(page.getByText('2027')).toBeVisible({ timeout: 10000 });
  });
});

// =============================================================================
// TEST SUITE: No False Catering Detection
// =============================================================================

test.describe('Catering Detection: No False Positives', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('dinner event should NOT trigger catering Q&A', async ({ page }) => {
    /**
     * Regression test: "dinner" as event type should NOT trigger catering section
     * The word "dinner" describes the event, not a question about catering
     */
    const email = testEmail();

    const inquiry = `Subject: Private Dinner
From: ${email}

Hi, I'd like to book a private dinner for 25 guests on May 20, 2026.

Best regards`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Should get room availability
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Should NOT show "Menu Options" - dinner is event type, not catering Q&A
    const menuOptions = page.getByText('Menu Options');
    await expect(menuOptions).not.toBeVisible();

    // Should show "Additional Information" instead
    await expect(page.getByText('Additional Information')).toBeVisible();
  });

  test('explicit catering question SHOULD trigger catering Q&A', async ({ page }) => {
    /**
     * When user explicitly asks about catering, we SHOULD show catering info
     */
    const email = testEmail();

    const inquiry = `Subject: Event Inquiry
From: ${email}

Hi, we need a room for 20 people on July 15, 2026.
What catering options do you have available?

Thanks`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Should get room availability
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Explicit catering question should trigger catering info
    await expect(page.getByText(/catering|menu|food options/i)).toBeVisible({ timeout: 10000 });
  });
});

// =============================================================================
// TEST SUITE: No Fallback Messages
// =============================================================================

test.describe('No Fallback Messages', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('clear event request should NOT trigger manual review', async ({ page }) => {
    /**
     * A message with date + participants should be recognized as event request
     * and NOT fall back to "routed for manual review"
     */
    const email = testEmail();

    const inquiry = `Subject: Event Booking
From: ${email}

Hi, I would like to book a room for 30 people on August 10, 2026.
Looking forward to your response.

Best`;

    await sendMessage(page, inquiry);
    await waitForResponse(page);

    // Should get room availability - NOT fallback message
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Should NOT see fallback/manual review message
    const fallback = page.getByText('routed it for manual review');
    await expect(fallback).not.toBeVisible();
  });
});

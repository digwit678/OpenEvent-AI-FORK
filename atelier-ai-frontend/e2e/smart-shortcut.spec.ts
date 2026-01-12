/**
 * Smart Shortcut E2E Tests
 *
 * Tests the smart shortcut flow where a complete event request
 * (date + participants + room preference) skips directly to Step 4 (offer).
 *
 * Run these tests:
 *   cd atelier-ai-frontend && npm run test:e2e
 */

import { test, expect, Page } from '@playwright/test';

// Helper: Generate unique test email
function testEmail(): string {
  const timestamp = Date.now();
  return `shortcut-${timestamp}@test.example.com`;
}

// Helper: Send a message in the chat UI
async function sendMessage(page: Page, message: string): Promise<void> {
  const textarea = page.getByRole('textbox');
  await textarea.waitFor({ state: 'visible' });
  await textarea.fill(message);
  const sendButton = page.getByRole('button', { name: 'Send' });
  await sendButton.click();
}

// Helper: Wait for assistant response
async function waitForResponse(page: Page, timeout = 60000): Promise<string> {
  try {
    await page.getByText('Shami is typing...').waitFor({ state: 'visible', timeout: 10000 });
    await page.getByText('Shami is typing...').waitFor({ state: 'hidden', timeout });
  } catch {
    // Typing indicator might not appear or already gone
  }
  await page.waitForTimeout(2000);
  const content = await page.locator('.prose, [class*="markdown"], p').allTextContents();
  return content.join('\n');
}

// =============================================================================
// TEST SUITE: Smart Shortcut - Complete Request Skips to Offer
// =============================================================================

test.describe('Smart Shortcut: Complete Request to Offer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('complete event request with room preference skips to offer HIL', async ({ page }) => {
    /**
     * Scenario: User provides date + participants + room in first message
     * Expected: System skips date confirmation and room selection, goes to offer
     */
    const email = testEmail();

    const completeInquiry = `Subject: Corporate Workshop
From: ${email}

Hi, we'd like to book Room B for a corporate workshop.
Date: March 20, 2026
Participants: 25 people
Duration: 9:00 to 17:00

Thanks,
Corporate Team`;

    await sendMessage(page, completeInquiry);
    await waitForResponse(page);

    // Should skip directly to offer review (Step 4)
    // Room should be auto-selected based on preference
    await expect(page.getByText('Room B').first()).toBeVisible({ timeout: 30000 });

    // Should show HIL task for offer review
    await expect(page.getByText('Manager Tasks')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/offer|review/i)).toBeVisible();

    // Should NOT show date alternatives (date was complete)
    const dateAlternatives = page.getByText('available dates');
    await expect(dateAlternatives).not.toBeVisible();
  });

  test('complete request with past date should reject and show alternatives', async ({ page }) => {
    /**
     * Scenario: User provides all details but date is in the past
     * Expected: System rejects past date and shows alternatives
     */
    const email = testEmail();

    // Use a past date (January 5, 2026 when test runs after that)
    const pastDateInquiry = `Subject: Event Inquiry
From: ${email}

Hi, we need Room A for a meeting.
Date: January 5, 2026
Participants: 15

Best regards`;

    await sendMessage(page, pastDateInquiry);
    await waitForResponse(page);

    // Should show rejection message with alternatives
    await expect(page.getByText(/past|already passed|alternative/i)).toBeVisible({ timeout: 30000 });

    // Should NOT proceed to offer (date invalid)
    const offerTask = page.getByText('offer message');
    await expect(offerTask).not.toBeVisible();
  });

  test('incomplete request without room should show room availability', async ({ page }) => {
    /**
     * Scenario: User provides date + participants but no room preference
     * Expected: System shows room availability for selection
     */
    const email = testEmail();

    const noRoomInquiry = `Subject: Birthday Party
From: ${email}

Hi, I'd like to book a space for a birthday party.
Date: April 15, 2026
Number of guests: 40

Thanks!`;

    await sendMessage(page, noRoomInquiry);
    await waitForResponse(page);

    // Should show room availability options
    await expect(page.getByText('Availability overview')).toBeVisible({ timeout: 30000 });

    // Should show multiple room options
    await expect(page.getByText(/Room [ABC]/)).toBeVisible();

    // Should NOT have offer HIL yet (room not selected)
    const offerTask = page.getByText('offer message');
    await expect(offerTask).not.toBeVisible();
  });
});

// =============================================================================
// TEST SUITE: Smart Shortcut with Q&A
// =============================================================================

test.describe('Smart Shortcut: With Q&A Questions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('complete request + parking Q&A should process both', async ({ page }) => {
    /**
     * Scenario: Complete event request with Q&A in same message
     * Expected: Both workflow action and Q&A are processed
     */
    const email = testEmail();

    const hybridInquiry = `Subject: Team Meeting
From: ${email}

Hi, we'd like to book Room C for a team meeting on May 10, 2026.
We'll have 20 attendees from 10:00 to 16:00.

Also, what are the parking options nearby?

Thanks`;

    await sendMessage(page, hybridInquiry);
    await waitForResponse(page);

    // Should process the event request
    await expect(page.getByText('Room C').first()).toBeVisible({ timeout: 30000 });

    // Should also answer parking Q&A
    await expect(page.getByText(/parking|garage/i)).toBeVisible({ timeout: 10000 });

    // Should have HIL task for offer
    await expect(page.getByText('Manager Tasks')).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import fs from "fs";
import path from "path";

const shots = process.env.JOURNEY_SHOTS || path.join("test-results", "journey");
fs.mkdirSync(shots, { recursive: true });

test.describe("e2e-journey", () => {
  test("fresh course from the wizard through a fake Moodle grade", async ({ page }) => {
    test.setTimeout(360_000);
    page.setDefaultTimeout(30_000);
    await page.setViewportSize({ width: 1440, height: 900 });

    async function shot(name: string) {
      await page.setViewportSize({ width: 1440, height: 900 });
      const alerts = page.getByRole("alert");
      if ((await alerts.count()) > 0) {
        throw new Error(await alerts.first().innerText());
      }
      await page.screenshot({ path: path.join(shots, name), animations: "disabled" });
    }

    const email = process.env.TEST_USER_EMAIL || "professor@demo.uowd.ac.ae";
    const password = process.env.TEST_USER_PASSWORD || "ProfAssist-demo-1";
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(email);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole("button", { name: /^login$/i }).click();
    await page.waitForURL(/dashboard/);
    await expect(page.getByPlaceholder(/Ask anything/i)).toBeVisible();
    await shot("journey-01.png");

    await page.goto("/outline?fresh=1");
    await expect(page.getByLabel("Subject name")).toBeVisible();
    await page.getByLabel("Subject name").fill("Assurance Studio");
    await page.getByLabel("Subject code").fill("AAS 910");
    await page.getByLabel("Credit points").fill("6");
    await page.getByLabel("Session").fill("Autumn");
    await page.getByLabel("Year").fill("2026");
    await page.getByLabel("Duration").fill("12 weeks");
    await page.getByLabel("Prerequisites").fill("None");
    await page.getByLabel("Delivery mode").fill("On campus");
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/step") && response.ok()),
      page.getByRole("button", { name: "Save draft" }).click(),
    ]);
    await page.getByRole("button", { name: "Next", exact: true }).click();

    await page.locator("input[type=file]").first().setInputFiles({
      name: "campus-notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "The campus clinic needs a four-week group project. Count arrivals and name who would use the count.\n",
      ),
    });
    await expect(page.getByText("campus-notes.txt")).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();

    for (const step of [
      "lecture",
      "description",
      "outcomes",
      "schedule",
      "readings",
      "assessments",
      "policies",
    ]) {
      await page.getByRole("button", { name: "Write a suggestion" }).click();
      await expect(page.getByText(new RegExp(`Suggested the ${step}`))).toBeVisible({
        timeout: 30_000,
      });
      await page.getByRole("button", { name: "Next", exact: true }).click();
    }

    await page.getByRole("button", { name: "Send for council review" }).click();
    await expect(page.getByText(/Score \d+/)).toBeVisible();
    await expect(page.getByText("Verdict reached.")).toBeVisible({ timeout: 40_000 });
    await page.getByText(/Score \d+/).scrollIntoViewIfNeeded();
    await shot("journey-03.png");

    await page.getByRole("button", { name: "Generate" }).click();
    await expect(page.getByText(/ready to download/)).toBeVisible({ timeout: 40_000 });
    await expect(page.getByRole("link", { name: "PDF" })).toBeVisible();
    await expect(page.getByRole("link", { name: "DOCX" })).toBeVisible();
    await shot("journey-02.png");

    await page.goto("/assignments");
    await page.getByRole("button", { name: "Group project" }).click();
    await expect(page.getByRole("heading", { name: /A3 Group project/ })).toBeVisible();
    await page.getByRole("tab", { name: "Ideas" }).click();
    await page.getByRole("button", { name: "Suggest ideas with council" }).click();
    await expect(page.getByText("Campus energy dashboard")).toBeVisible();
    await page.getByRole("tab", { name: "Exemplars" }).click();
    await page.getByRole("button", { name: "Write exemplar" }).click();
    await expect(page.getByText(/Strong:/).first()).toBeVisible();
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page.getByText("Problem definition")).toBeVisible();
    await page.getByRole("button", { name: "Form groups of two" }).click();
    await expect(page.getByText(/groups are ready/)).toBeVisible();
    await page.getByRole("button", { name: "Publish to Moodle" }).click();
    await expect(page.getByText(/Published to Moodle/)).toBeVisible();
    await expect(page.getByText("published").first()).toBeVisible();
    await shot("journey-04.png");

    await page.getByRole("button", { name: "Sync student submissions" }).click();
    await expect(page.getByText(/submissions synced/)).toBeVisible({ timeout: 120_000 });
    await page.getByRole("tab", { name: "Submissions" }).click();
    await expect(page.getByText("Group A").first()).toBeVisible();
    await expect(page.getByText("Group B").first()).toBeVisible();
    await expect(page.getByText("Group C").first()).toBeVisible();
    await shot("journey-05.png");

    await page.goto("/integrity?course=AAS910&assignment=A3&pair=A-B");
    await expect(page.getByRole("heading", { name: "Group A and Group B" })).toBeVisible({
      timeout: 120_000,
    });
    await page.getByRole("button", { name: "See in document" }).click();
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 40_000 });
    await shot("journey-06.png");

    await page.goto("/grade");
    const total = page.locator(".pa-grade-total");
    await expect(total).toBeVisible({ timeout: 60_000 });
    const before = (await total.innerText()).trim();
    await page.getByRole("button", { name: "Change this row" }).nth(1).click();
    await page.getByRole("button", { name: /Fair/ }).click();
    await expect(page.getByText("Changed by you")).toBeVisible();
    await expect(total).not.toHaveText(before, { timeout: 10_000 });
    await page.getByLabel("Margin comment").fill("Please say who would use this count.");
    await page.getByRole("button", { name: "Add margin comment" }).click();
    await expect(page.getByText("Please say who would use this count.")).toBeVisible();
    await shot("journey-07.png");

    await page.getByRole("button", { name: "Approve grade" }).click();
    await page.getByRole("button", { name: "Send to Moodle" }).click();
    await expect(page.getByText("Sent to Moodle").first()).toBeVisible({ timeout: 40_000 });
    await expect(page.getByText(/This assignment is complete/)).toBeVisible();
    await expect(page.getByText(/Moodle was not contacted/)).toBeVisible();
    await shot("journey-08.png");

    await page.goto("/assignments");
    await expect(page.getByText("complete").first()).toBeVisible();

    await page.goto("/students");
    await expect(page.getByText(/AAS910/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Students who may need help" })).toBeVisible();
    await expect(page.getByText("Synthetic, demo only")).toBeVisible();
    await expect(page.getByText("Sara Al Maktoum")).toBeVisible();
    await shot("journey-09.png");
  });
});

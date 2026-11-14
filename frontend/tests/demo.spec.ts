import { test, expect } from "@playwright/test";
test("2D overlays, mission interactions, blocked events and playback", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/map-preview.html");
  await expect(page.getByTestId("map-2d")).toBeVisible();
  await expect(page.locator(".leaflet-image-layer")).toBeVisible();
  await page.screenshot({ path: "../screenshots/2d-demo.png", fullPage: true });
  await page.getByRole("checkbox", { name: "hazard visibility" }).check();
  await expect(page.locator(".leaflet-image-layer")).toHaveCount(2);
  await page.getByRole("slider", { name: "hazard opacity" }).fill("0.3");
  await page.getByRole("checkbox", { name: "hazard visibility" }).uncheck();
  await expect(page.locator(".leaflet-image-layer")).toHaveCount(1);
  await page.getByRole("button", { name: /Western outcrop/ }).click();
  await expect(page.locator(".target-card.selected")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Play astronaut simulation", exact: false })
    .click();
  await expect(page.locator(".astronaut-icon")).toBeVisible();
  await page
    .getByRole("button", { name: "Pause playback", exact: false })
    .click();
  await page.getByRole("button", { name: "Block", exact: true }).click();
  const map = page.getByTestId("map-2d");
  await map.click({ position: { x: 350, y: 250 } });
  await map.click({ position: { x: 440, y: 330 } });
  await page
    .getByRole("textbox", { name: "Blocked area reason" })
    .fill("Synthetic obstruction");
  await page.getByRole("button", { name: "Confirm block" }).click();
  await expect(
    page.getByText("Synthetic obstruction", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Replan pending/)).toBeVisible();
  await page.getByRole("button", { name: "Apply fixture response" }).click();
  await expect(page.getByText(/Replan pending/)).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("DEM terrain renders, orbit works, selection persists and missing DEM is explicit", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/map-preview.html");
  await page.getByRole("button", { name: /Western outcrop/ }).click();
  await page.getByRole("button", { name: "3D Terrain" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(
    page.getByText("DEM-derived surface", { exact: false }),
  ).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "../screenshots/3d-demo.png", fullPage: true });
  const box = await page.locator("canvas").boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.6, {
      steps: 12,
    });
    await page.mouse.up();
  }
  await page.getByRole("slider", { name: "Vertical exaggeration" }).fill("2");
  await expect(
    page.getByText("DEM-derived surface · 2× height", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "2D Map" }).click();
  await expect(page.locator(".target-card.selected")).toHaveCount(1);
  await page.getByLabel("Test scenario").selectOption("no-dem");
  await page.getByRole("button", { name: "3D Terrain" }).click();
  await expect(page.getByText("3D terrain unavailable")).toBeVisible();
  await page.getByLabel("Test scenario").selectOption("bad-projection");
  await expect(page.getByText(/Unsupported DEM projection/)).toBeVisible();
  expect(errors).toEqual([]);
});
test("no data, no route and image failure are visible", async ({ page }) => {
  await page.goto("/map-preview.html");
  await page.getByLabel("Test scenario").selectOption("no-route");
  await expect(
    page.locator(".warning").filter({ hasText: "No feasible route" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Play astronaut simulation",
      exact: false,
    }),
  ).toBeDisabled();
  await page.getByLabel("Test scenario").selectOption("image-error");
  await page.locator(".layer").first().locator("summary").click();
  await expect(
    page.getByText("Image unavailable", { exact: false }),
  ).toBeVisible();
  await page.getByLabel("Test scenario").selectOption("no-data");
  await expect(
    page.getByText("No processed layers. Coverage is unknown."),
  ).toBeVisible();
});
test("mobile viewport has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/map-preview.html");
  await expect(page.getByTestId("map-2d")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../screenshots/mobile-demo.png",
    fullPage: true,
  });
});

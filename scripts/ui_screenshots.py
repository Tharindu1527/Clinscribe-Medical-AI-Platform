"""Screenshots of the review UI for the docs (docs/presentation/ui/), from demo mode.

Demo mode (`npm --prefix apps/web run dev:demo`) answers from responses recorded from the real API
on synthetic data (apps/web/src/demo/fixtures.json), so these pictures need no stack and show no
real patient. Playwright drives the installed Chrome headless (no browser download); it is not a
project dependency.

  npm --prefix apps/web run dev:demo -- --port 5174     (in another terminal)
  just ui-screenshots
"""

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import (  # type: ignore[import-not-found, unused-ignore]
    Page,
    async_playwright,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "presentation" / "ui"


async def sign_in(page: Page, url: str, user: str) -> None:
    await page.goto(url)
    await page.get_by_role("radio", name=user).click()
    await page.get_by_role("button", name="Continue as").click()
    await page.wait_for_selector(".sidebar")


async def shoot(page: Page, name: str, theme: str) -> None:
    path = OUT / f"{name}-{theme}.png"
    await page.screenshot(path=str(path))
    print(f"wrote {path.relative_to(ROOT)}")


async def run(url: str, theme: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900}, device_scale_factor=1, color_scheme=theme
        )
        page = await context.new_page()
        await page.goto(url)
        await shoot(page, "sign-in", theme)

        await sign_in(page, url, "Dr Demo")
        await page.get_by_role("button", name="Does clarithromycin interact with warfarin?").click()
        await page.wait_for_selector(".answer-text", timeout=15000)
        await page.locator(".cite").nth(1).hover()
        await page.wait_for_timeout(400)  # the highlight fades in
        await shoot(page, "ask", theme)

        await page.get_by_role("button", name="Scribe").click()
        await page.get_by_role("button", name="Review").first.click()
        await page.wait_for_selector(".statement")
        await page.locator(".statement.unsure").last.hover()
        await page.mouse.wheel(0, 240)
        await page.wait_for_timeout(400)
        await shoot(page, "scribe-review", theme)

        await page.get_by_role("button", name="Lab").click()
        await page.get_by_role("button", name="Load the demo message").click()
        await page.get_by_role("button", name="Read the report").click()
        await page.wait_for_selector("table.table")
        await page.locator("table.table").scroll_into_view_if_needed()
        await page.wait_for_timeout(300)
        await shoot(page, "lab", theme)

        await page.get_by_role("button", name="Sign out").click()
        await sign_in(page, url, "Admin Demo")
        await page.wait_for_selector("table.table")
        await shoot(page, "audit", theme)
        await browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:5174")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    args = parser.parse_args(argv)
    asyncio.run(run(args.url, args.theme))
    return 0


if __name__ == "__main__":
    sys.exit(main())

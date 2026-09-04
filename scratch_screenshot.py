import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        print("Visiting IDX page...")
        try:
            await page.goto("https://www.idx.co.id/id/data-pasar/ringkasan-transaksi/ringkasan-broker/", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Goto error: {e}")
        
        print("Taking screenshot...")
        await page.screenshot(path="idx_broksum_page.png", full_page=True)
        
        # Let's also print the basic HTML structure around inputs to help us
        html = await page.content()
        with open("idx_broksum_html.html", "w") as f:
            f.write(html)
            
        await browser.close()
        print("Done.")

asyncio.run(main())

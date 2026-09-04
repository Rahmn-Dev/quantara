import asyncio
from playwright.async_api import async_playwright

cookie_val = "{%22state%22:{%22access%22:{%22token%22:%22eyJhbGciOiJSUzI1NiIsImtpZCI6ImExNWQ5OGE2LTdkYzgtNDM3NS05NDk0LTEyOWJlM2RlODVkNCIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7InVzZSI6IlJhaG1uMjEiLCJlbWEiOiJzaWRxaS5yYWhtYW5AZ21haWwuY29tIiwiZnVsIjoiUmFobWFuIiwic2VzIjoiMWJWZm1wUFF3azZMUFJOdSIsImR2YyI6ImVhZDU2ZDljOWRhYWYzZmRhZjAzYWJiZTVjYjVhODFlIiwidWlkIjozNzg0NDI3LCJjb3UiOiJJRCJ9LCJleHAiOjE3ODg1Njk3MzYsImlhdCI6MTc4ODQ4MzMzNiwiaXNzIjoiU1RPQ0tCSVQiLCJqdGkiOiJiNDUzODI3MC02Yzg0LTQ1NWYtYmJiZC00MjIxNGJiYWQ2YTQiLCJuYmYiOjE3ODg0ODMzMzYsInZlciI6InYxIn0.LAmqjADKZmyn2LxPpjnNFUnYHtHQQJdadWgBuUGs2LHuuV1ycWhGiPqwgtrGYTr_fbAqFNTOFSn5Xl12cRJYWPKqNleLSydzhHunNY3a8ZDo9LqYyTRMWOXNPQMB4PZ9Pc6AhdSj4I5DzYONmShXiLldSR63KcFbNcSHsgaIoeld3tUrMqZK1_9Kbyw3QvRYvjER5ji2d6eTdRCHB5CXUINbyooILCeGc6LQ0b_sn-XR5UOOsNQRrOURfzHcPOoCMJGnhLjwF6tWWNjKl3UhYp1TwN6Bw8vShvKbecHOHwhaPrnrxwSKiM6VNVEWWTuEDfuGfVCs3PDHkWZ9DtSuIg%22%2C%22expired_at%22:%222026-09-05T00:55:36Z%22}%2C%22refresh%22:{%22token%22:%22eyJhbGciOiJSUzI1NiIsImtpZCI6ImExNWQ5OGE2LTdkYzgtNDM3NS05NDk0LTEyOWJlM2RlODVkNCIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7InR5cCI6InJlZnJlc2giLCJ1c2UiOiJSYWhtbjIxIiwiZW1hIjoic2lkcWkucmFobWFuQGdtYWlsLmNvbSIsImZ1bCI6IlJhaG1hbiIsInNlcyI6IjFiVmZtcFBRd2s2TFBSTnUiLCJkdmMiOiJlYWQ1NmQ5YzlkYWFmM2ZkYWYwM2FiYmU1Y2I1YTgxZSIsInVpZCI6Mzc4NDQyNywiY291IjoiSUQifSwiZXhwIjoxNzg5MDg4MTM2LCJpYXQiOjE3ODg0ODMzMzYsImlzcyI6IlNUT0NLQklUIiwianRpIjoiYjQ1MzgyNzAtNmM4NC00NTVmLWJiYmQtNDIyMTRiYmFkNmE0IiwibmJmIjoxNzg4NDgzMzM2LCJ2ZXIiOiJ2MSJ9.DAngtR6Yh7l_EGrpr9ImWE4ZEpoSz3IARhBzpYmVlPIwNCTVia5QN08advZVd9_OPZzKdJPKcmviVE_N4tWsNmq91dogx2cfa2CitXVDJFEwJZ-fFzj1XgpRt7PYZbOTnv3lfPdLEglJKOBoS6S3kT9uEzsNw0wm9C81KJMk2ZxvV0qTtbXGkMCU77imMB3YoC3uevTwkEgXuNmdPTFnwp5dPiLnBqrqgBdP92CmoulBvPIDJ5bfDj6xEutbXZLnUc9QUqZ3TGPovfBn-XHXeq6rJozcSAqjWk93XAEJqTBX6Vq1JESE-r3QoQfzfgVJfSkxgjHznwVxoHL1ny0KFQ%22%2C%22expired_at%22:%222026-09-11T00:55:36Z%22}%2C%22user%22:{%22id%22:3784427%2C%22username%22:%22Rahmn21%22%2C%22country%22:%22ID%22%2C%22watchlist_id%22:7181074%2C%22privilege%22:{%22code%22:0}}}%2C%22version%22:0}"

cookies = [{"name": "credentialStorage", "value": cookie_val, "domain": "stockbit.com", "path": "/"}]

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        await context.add_cookies(cookies)
        page = await context.new_page()
        
        captured_api = []
        async def handle_response(response):
            if "graphql" in response.url.lower() or "broker" in response.url.lower():
                try:
                    data = await response.json()
                    captured_api.append((response.url, data))
                except:
                    pass
        
        page.on("response", handle_response)

        try:
            print("Visiting Broker Analysis...")
            # Navigate directly to broker analysis URL if known, else go to home and click
            await page.goto("https://stockbit.com/broker", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(5000)
            
            # Fill the stock symbol (BBCA)
            # Typically there's an input for symbol
            symbol_input = page.locator("input[placeholder*='symbol']").first
            if await symbol_input.count() > 0:
                print("Found symbol input, typing BBCA...")
                await symbol_input.fill("BBCA")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)
            else:
                print("Could not find symbol input, checking HTML for inputs")
            
            await page.screenshot(path="stockbit_broker_analysis.png", full_page=True)
            print("Taking screenshot...")
            
            # Write HTML to see the DOM
            html = await page.content()
            with open("stockbit_broker_analysis.html", "w") as f:
                f.write(html)
                
            # Log any captured API data
            print(f"Captured {len(captured_api)} possible API responses")
            for url, data in captured_api:
                if isinstance(data, dict):
                    print(url, list(data.keys()))
        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="stockbit_error.png")
            
        await browser.close()
        print("Done.")

asyncio.run(main())

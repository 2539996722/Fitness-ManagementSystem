"""截图 avatar modal 上传 tab 的样子。"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 1100})
        page = await context.new_page()

        await page.add_init_script("""
            localStorage.setItem('fithub_access_token', 'fake');
            localStorage.setItem('fithub_refresh_token', 'fake');
            localStorage.setItem('fithub_user', JSON.stringify({
                id: 34, username: 'demo_user', nickname: '演示昵称',
                avatar_url: null, role: 'user', status: 0
            }));
        """)

        async def fulfill(route, body):
            await route.fulfill(status=200, content_type="application/json", body=body)
        await page.route("**/api/v1/users/me", lambda r: asyncio.create_task(fulfill(r,
            '{"id":34,"username":"demo_user","nickname":"演示昵称","avatar_url":null,"gender":1,"age":28,"height_cm":176,"weight_kg":72.5,"role":"user","status":0,"created_at":"2024-01-15T08:00:00","last_login_at":"2026-10-11T08:30:00"}')))
        await page.route("**/api/v1/plans/", lambda r: asyncio.create_task(fulfill(r, '[]')))
        await page.route("**/api/v1/users/me/weight-logs*", lambda r: asyncio.create_task(fulfill(r, '{"items":[],"total":0}')))
        await page.route("**/api/v1/conversations", lambda r: asyncio.create_task(fulfill(r, '[]')))
        await page.route("**/api/v1/users/me/reviews*", lambda r: asyncio.create_task(fulfill(r, '{"items":[],"total":0,"page":1,"page_size":10,"has_more":false}')))
        await page.route(lambda url: "/plans/" in url and "/records" in url,
                         lambda r: asyncio.create_task(fulfill(r, "[]")))

        await page.goto("http://127.0.0.1:8000/c/profile.html", timeout=20000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        # 截图 1: 默认页面（未打开 modal）
        await page.screenshot(path="E:/profile_normal.png", full_page=False)

        # 点击头像 → 弹 modal
        await page.click("#heroAvatar")
        await page.wait_for_timeout(500)

        # 截图 2: 默认 URL tab
        await page.screenshot(path="E:/profile_modal_url.png", full_page=False)

        # 切换到 Upload tab
        await page.click('.avatar-tabs__btn[data-tab="upload"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path="E:/profile_modal_upload.png", full_page=False)

        for f in ['E:/profile_normal.png', 'E:/profile_modal_url.png', 'E:/profile_modal_upload.png']:
            sz = Path(f).stat().st_size
            print(f"{f}: {sz} bytes")

        await browser.close()


asyncio.run(main())

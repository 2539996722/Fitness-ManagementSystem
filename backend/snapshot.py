"""截图 profile.html 给用户看真实渲染效果。"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 1800})
        page = await context.new_page()

        # 注入 token 到 localStorage（绕过登录）
        await page.add_init_script("""
            localStorage.setItem('fithub_access_token', 'fake');
            localStorage.setItem('fithub_refresh_token', 'fake');
            localStorage.setItem('fithub_user', JSON.stringify({
                id: 34, username: 'demo_user', nickname: '演示昵称',
                avatar_url: null, role: 'user', status: 0
            }));
        """)

        # 让 fetch 失败时不抛出错误（避免白屏）
        await page.route("**/api/v1/users/me", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"id":34,"username":"demo_user","nickname":"演示昵称","avatar_url":null,"gender":1,"age":28,"height_cm":176,"weight_kg":72.5,"role":"user","status":0,"created_at":"2024-01-15T08:00:00","last_login_at":"2026-10-11T08:30:00"}'
        ))
        await page.route("**/api/v1/plans/", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='[{"id":1,"user_id":34,"name":"增肌计划","goal":"muscle_gain","is_current":1,"days_per_week":4,"created_at":"2024-03-01T08:00:00","updated_at":"2024-03-01T08:00:00","weeks":[{"week":1,"days":[{"day":1,"exercises":[{"exercise_id":"0001"}]},{"day":3,"exercises":[{"exercise_id":"0030"}]}]}],"total_days":2,"completed_days":1,"progress_pct":50.0,"thumbnails":[]}]'
        ))
        await page.route("**/api/v1/users/me/weight-logs*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"items":[{"id":1,"weight_kg":73.2,"recorded_at":"2026-09-15T08:00:00","note":"早起","created_at":"2026-09-15T08:00:00"},{"id":2,"weight_kg":72.8,"recorded_at":"2026-09-22T08:00:00","note":"","created_at":"2026-09-22T08:00:00"},{"id":3,"weight_kg":72.5,"recorded_at":"2026-09-29T08:00:00","note":"训练后","created_at":"2026-09-29T08:00:00"},{"id":4,"weight_kg":72.0,"recorded_at":"2026-10-06T08:00:00","note":"","created_at":"2026-10-06T08:00:00"}],"total":4}'
        ))
        await page.route("**/api/v1/conversations", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='[{"id":121,"user_id":34,"title":"新手每周练几次健身合适","status":"ai_active","conversation_type":"ai","created_at":"2026-10-11T11:10:54","updated_at":"2026-10-11T11:10:54","last_message":"对于新手来说，每周进行3-4次健身是比较合适的"},{"id":118,"user_id":34,"title":"胸肌怎么练","status":"ai_active","conversation_type":"ai","created_at":"2026-10-09T15:23:11","updated_at":"2026-10-10T18:42:33","last_message":"试试标准卧推，3 组 8-12 次"}]'
        ))
        await page.route("**/api/v1/users/me/reviews*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"items":[{"id":1,"exercise_id":"0001","exercise_name_zh":"标准卧推","rating":5,"content":"动作要领讲得很清楚","status":0,"created_at":"2024-03-15T10:30:00","updated_at":"2024-03-15T10:30:00"},{"id":2,"exercise_id":"0030","exercise_name_zh":"深蹲","rating":4,"content":"适合新手","status":0,"created_at":"2024-03-20T14:22:00","updated_at":"2024-03-20T14:22:00"}],"total":2,"page":1,"page_size":10,"has_more":false}'
        ))
        # plan records — 简单返回空
        await page.route(lambda url: "/plans/" in url and "/records" in url,
                         lambda route: route.fulfill(status=200, content_type="application/json", body="[]"))

        await page.goto("http://127.0.0.1:8000/c/profile.html", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)  # 等 chart.js 渲染

        # 截图（整页）
        out = Path("E:/profile_screenshot.png")
        await page.screenshot(path=str(out), full_page=True)
        print(f"✅ 截图保存: {out} ({out.stat().st_size} bytes)")

        # 同时输出页面渲染高度 / 关键元素 bounding box
        h = await page.evaluate("document.querySelector('.profile-page')?.offsetHeight")
        print(f"profile-page 渲染高度: {h}px")
        for sel in ['.hero', '.section-card', '.bmi-card', '.quick-actions']:
            box = await page.evaluate(f"""
                (() => {{
                    const el = document.querySelector('{sel}');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {{ w: Math.round(r.width), h: Math.round(r.height) }};
                }})()
            """)
            print(f"  {sel}: {box}")

        await browser.close()


asyncio.run(main())

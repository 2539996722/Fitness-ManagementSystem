// ============ C 端首页 Banner 加载（M9）============
// 拉取 /api/v1/banners/active，渲染到 #bannerStrip。
// 单条 banner：横向卡片；多条：横向滚动轮播。
// 失败静默（公告挂了不能影响主流程）。

const strip = document.getElementById('bannerStrip');
if (strip) {
    loadBanners().catch(() => { /* 静默 */ });
}

async function loadBanners() {
    const resp = await fetch('/api/v1/banners/active');
    if (!resp.ok) return;
    const items = await resp.json();
    if (!items || items.length === 0) {
        strip.hidden = true;
        return;
    }
    strip.hidden = false;
    strip.className = items.length > 1 ? 'banner-strip banner-strip--multi' : 'banner-strip';
    strip.innerHTML = items.map((b, i) => `
        <article class="banner-card${i === 0 ? ' banner-card--head' : ''}" data-link="${esc(b.link_url || '')}">
            <span class="banner-card__tag">公告</span>
            <h3 class="banner-card__title">${esc(b.title)}</h3>
            <p class="banner-card__content">${esc(b.content)}</p>
            ${b.link_url ? `<span class="banner-card__arrow">→</span>` : ''}
        </article>
    `).join('');
    strip.addEventListener('click', e => {
        const card = e.target.closest('.banner-card');
        if (!card) return;
        const url = card.dataset.link;
        if (url) window.location.href = url;
    });
}

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
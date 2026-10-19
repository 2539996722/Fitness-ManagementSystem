// 谭师动作库 — 详情页
const API = '/api/v1';

const params = new URLSearchParams(location.search);
// 兼容两种来源：?id=xxx（谭师库列表）或 ?actionId=xxx（训练计划）
const id = params.get('id') || params.get('actionId');
const root = document.getElementById('content');

function platform(url) {
    if (url.includes('bilibili.com')) return { name: 'B站', cls: 'bilibili' };
    if (url.includes('douyin.com')) return { name: '抖音', cls: 'douyin' };
    return { name: '视频', cls: '' };
}

function fmtTime(sec) {
    if (typeof sec !== 'number') return '';
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
}

function escape(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function render(a) {
    const g = a.guide || {};
    const m = a.media || {};
    const tp = a.training_profile || {};
    const dose = a.training || {};
    const thumb = m.src ? `/c/${m.src}` : '';
    const _src = m.source || {};
    let playUrl = _src.url || (g.watch_primary && g.watch_primary.url) || '#';
    // 给 B 站链接附加 ?p=时间戳（秒），让"去 B 站"直接跳到该动作对应片段
    if (playUrl.includes('bilibili.com') && typeof _src.start === 'number') {
        try {
            const u = new URL(playUrl);
            u.searchParams.set('p', String(Math.round(_src.start)));
            playUrl = u.toString();
        } catch (e) { /* keep original */ }
    }
    const platformLabel = playUrl.includes('bilibili') ? 'B站' : (playUrl.includes('douyin') ? '抖音' : '视频');
    // 三态：default / loading / error
    // 进入页面：先显示缩略图（用户点"载入预览"才进 loading）；
    // 若想加"自动模拟加载"，可在 mount 后 800ms 自动切到 loading，2s 后看 url 是否可达
    const videoState = 'default';

    const steps = (g.steps || []).map((s, i) => `
        <div class="tan-step">
            <div class="tan-step__num">步骤 ${i + 1}</div>
            <h4>${escape(s.title)}</h4>
            <p>${escape(s.text)}</p>
        </div>
    `).join('');

    const points = (g.key_points || []).map(p => `
        <div class="tan-point">
            <h4>${escape(p.title)}</h4>
            <p>${escape(p.text)}</p>
        </div>
    `).join('');

    const sources = (g.sources || []).map(s => {
        const p = platform(s.url || '');
        const range = s.start != null ? `${fmtTime(s.start)} – ${fmtTime(s.end)}` : '';
        return `
        <a class="tan-source" href="${escape(s.url)}" target="_blank" rel="noreferrer">
            <div class="tan-source__main">
                <div class="tan-source__label">${escape(s.label || s.title || '源视频片段')}</div>
                <div class="tan-source__meta">${escape(s.video_id || '')} ${range ? '· ' + range : ''}</div>
            </div>
            <span class="tan-source__platform tan-source__platform--${p.cls}">${p.name}</span>
            <span class="tan-source__arrow">↗</span>
        </a>`;
    }).join('');

    // 解析 URL 参数：返回链接 / 训练计划上下文
    const _urlParams = new URLSearchParams(location.search);
    const _backPlan = _urlParams.get('plan');
    const _backDay = _urlParams.get('day');
    const _backHref = (_backPlan && _backDay)
        ? `tan-plan.html?name=${encodeURIComponent(_backPlan)}&day=${encodeURIComponent(_backDay)}`
        : 'tan-library.html';
    const _backLabel = (_backPlan && _backDay) ? `返回第 ${_backDay} 天` : '返回动作库';

    root.innerHTML = `
        <a class="tan-detail__back" href="${_backHref}">‹ ${_backLabel}</a>
        <div class="tan-detail__header">
            <div class="tan-guide-hero" data-state="${videoState}">
                ${thumb ? `<img class="tan-guide-hero__img" src="${escape(thumb)}" alt="${escape(a.name)}" onerror="this.style.display='none'">` : ''}
                <div class="tan-guide-hero__fallback" style="display:none;">
                    <div class="tan-guide-hero__fallback-icon">🎬</div>
                    <div class="tan-guide-hero__fallback-text">视频加载失败</div>
                </div>
                <div class="tan-guide-hero__loader" style="display:none;">
                    <div class="tan-guide-hero__spinner"></div>
                    <div class="tan-guide-hero__loader-text">载入预览中…</div>
                </div>
                <div class="tan-guide-hero__overlay">
                    ${m.creator ? `<span class="tan-guide-hero__origin">@ ${escape(m.creator)}</span>` : ''}
                    <button class="tan-guide-hero__play" data-action="load-preview" type="button">▶ 载入预览</button>
                    ${playUrl !== '#' ? `<a class="tan-guide-hero__external" href="${escape(playUrl)}" target="_blank" rel="noreferrer">去 ${platformLabel} 观看完整</a>` : ''}
                </div>
            </div>
            <div class="tan-meta">
                <div class="tan-meta__eyebrow">${escape(a.body || '')}</div>
                <h1>${escape(a.name)}</h1>
                <div>
                    <span class="tan-meta__chip">${escape(a.equipment?.[0] || '无器械')}</span>
                    ${a.equipment?.slice(1, 3).map(e => `<span class="tan-meta__chip">${escape(e)}</span>`).join('') || ''}
                </div>
                <p class="tan-meta__summary">${escape(g.summary || '')}</p>
                ${(g.muscles || []).length ? `
                <div class="tan-meta__muscles">
                    ${g.muscles.map(m => `<span>${escape(m)}</span>`).join('')}
                </div>` : ''}
            </div>
        </div>

        ${steps ? `
        <section class="tan-section">
            <h2>分步</h2>
            <div class="tan-steps">${steps}</div>
        </section>` : ''}

        ${points ? `
        <section class="tan-section">
            <h2>关键要点</h2>
            <div class="tan-points">${points}</div>
        </section>` : ''}

        ${(dose.displayDose || dose.joint || dose.purpose) ? `
        <section class="tan-section">
            <h2>训练配置</h2>
            <div class="tan-dose">
                <div class="tan-dose__row">
                    ${dose.joint ? `<div><b>关节类型</b><span>${escape(dose.joint)}</span></div>` : ''}
                    ${dose.purpose ? `<div><b>训练目的</b><span>${escape(dose.purpose)}</span></div>` : ''}
                    ${dose.displayDose ? `<div><b>推荐剂量</b><span>${escape(dose.displayDose)}</span></div>` : ''}
                </div>
            </div>
        </section>` : ''}

        ${sources ? `
        <section class="tan-section">
            <h2>源视频（${(g.sources || []).length}）</h2>
            <div class="tan-sources">${sources}</div>
        </section>` : ''}
    `;
}

(async () => {
    if (!id) {
        root.innerHTML = '<div class="tan-error"><b>未指定动作 ID</b></div>';
        return;
    }
    try {
        const r = await fetch(`${API}/tan-actions/${encodeURIComponent(id)}`);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const a = await r.json();
        document.title = `${a.name} · 谭师动作库`;
        render(a);
        bindHeroStateMachine();
    } catch (e) {
        root.innerHTML = `<div class="tan-error"><b>加载失败</b><br>${escape(e.message)}</div>`;
    }
})();

// 视频区三态状态机
// state: 'default'（缩略图+载入预览按钮）→ 'loading'（载入预览中）→ 'loaded'（成功）或 'error'（失败）
// 不嵌入 B 站/抖音视频；点击"载入预览"仅做一次模拟（dataset 没有真实视频源），失败后引导用户去外链
function bindHeroStateMachine() {
    const hero = document.querySelector('.tan-guide-hero');
    if (!hero) return;
    const img = hero.querySelector('.tan-guide-hero__img');
    const fallback = hero.querySelector('.tan-guide-hero__fallback');
    const loader = hero.querySelector('.tan-guide-hero__loader');
    const overlay = hero.querySelector('.tan-guide-hero__overlay');
    const btn = hero.querySelector('[data-action="load-preview"]');

    function setState(s) {
        hero.dataset.state = s;
        if (s === 'loading') {
            img.style.display = 'none';
            fallback.style.display = 'none';
            loader.style.display = 'flex';
            overlay.style.display = 'none';
        } else if (s === 'loaded') {
            loader.style.display = 'none';
            fallback.style.display = 'none';
            img.style.display = '';
            overlay.style.display = 'flex';
        } else if (s === 'error') {
            loader.style.display = 'none';
            img.style.display = 'none';
            fallback.style.display = 'flex';
            overlay.style.display = 'flex';
        } else {
            // default
            img.style.display = '';
            loader.style.display = 'none';
            fallback.style.display = 'none';
            overlay.style.display = 'flex';
        }
    }

    // 缩略图加载失败 → 直接 error 态
    if (img) {
        img.addEventListener('error', () => {
            if (hero.dataset.state === 'default') setState('error');
        });
    }

    // 点"载入预览"：模拟一次加载（dataset 没有真实视频源，2s 后 fallback 到 error）
    if (btn) {
        btn.addEventListener('click', () => {
            setState('loading');
            // 模拟加载：1.5s 后若缩略图已显示 + 视频源不可用 → 切到 error
            setTimeout(() => {
                if (img && img.complete && img.naturalWidth > 0) {
                    setState('loaded');
                } else {
                    setState('error');
                }
            }, 1500);
        });
    }
}

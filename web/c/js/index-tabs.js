// index-tabs.js — 单页 Tab 切换（主导航在 .navbar 内）
//
// 行为：
// - 4 个面板 (#panel-exercises / #panel-plans / #panel-templates / #panel-profile) 切换 hidden
// - 同步激活样式（navbar__link--active + aria-selected）
// - URL hash 同步（#exercises / #plans / #templates / #profile），刷新可恢复
// - 谭师库用独立 URL（tan-library.html），不参与同页切换

const TABS = document.querySelectorAll('.navbar__link[data-tab]');
const PANELS = document.querySelectorAll('.tab-panel');

const INLINE_TABS = new Set(['exercises', 'plans', 'templates', 'profile']);

function activate(name) {
    PANELS.forEach(p => {
        if (p.dataset.panel === name) p.removeAttribute('hidden');
        else p.setAttribute('hidden', '');
    });
    TABS.forEach(t => {
        const active = t.dataset.tab === name;
        t.classList.toggle('navbar__link--active', active);
        t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
}

TABS.forEach(tab => {
    tab.addEventListener('click', (e) => {
        const name = tab.dataset.tab;
        if (!name) return;
        // 谭师库 href 跳独立 URL，不拦截
        if (!INLINE_TABS.has(name)) return;
        e.preventDefault();
        activate(name);
        history.replaceState(null, '', `#${name}`);
    });
});

// 初始 hash 恢复
const initial = (location.hash || '').replace('#', '');
if (INLINE_TABS.has(initial)) activate(initial);
else activate('exercises');

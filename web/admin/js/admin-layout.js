// ============ 全局后台布局（侧边栏 + 用户信息 + 退出登录）============
// 由各 admin 页面用 `<script type="module" src="js/admin-layout.js"></script>` 引入
// 自动在 DOMContentLoaded 后挂载到 #appSidebar / #userName / #userRole / #logoutBtn

const ROLE_LABEL = { admin: '管理员', trainer: '教练', user: '用户' };

// 侧边栏菜单（统一顺序，data-requires-roles 走这里集中配置）
const MENU_ITEMS = [
    { key: 'dashboard',     href: '/admin/dashboard.html',     icon: '📊', label: '数据看板',     roles: ['admin', 'trainer'] },
    { key: 'users',         href: '/admin/users.html',         icon: '👥', label: '会员管理',     roles: ['admin', 'trainer'] },
    { key: 'workbench',     href: '/admin/workbench.html',     icon: '💬', label: '会话工作台',   roles: ['admin', 'trainer'] },
    { key: 'templates',     href: '/admin/templates.html',     icon: '📋', label: '计划模板',     roles: ['admin', 'trainer'] },
    { key: 'reviews',       href: '/admin/reviews.html',       icon: '⭐', label: '评论管理',     roles: ['admin'] },
    { key: 'banners',       href: '/admin/banners.html',       icon: '📢', label: '公告管理',     roles: ['admin'] },
    { key: 'operation-logs', href: '/admin/operation-logs.html', icon: '📜', label: '操作日志',    roles: ['admin'] },
    { key: 'traces',         href: '/admin/traces.html',         icon: '🔍', label: '链路追踪',     roles: ['admin'] },
    { key: 'knowledge-base', href: '/admin/knowledge-base.html', icon: '📚', label: '知识库',       roles: ['admin'] },
    { key: 'system-config', href: '/admin/system-config.html', icon: '⚙️', label: '系统配置',     roles: ['admin'] },
];

function getUser() {
    try { return JSON.parse(localStorage.getItem('fithub_admin_user') || 'null'); }
    catch { return null; }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
}

export function renderSidebar() {
    const root = document.getElementById('appSidebar');
    if (!root) return null;
    const user = getUser();
    if (!user) return null;

    const here = location.pathname.split('/').pop() || 'index.html';
    const isIndexLike = here === 'index.html';

    const itemsHtml = MENU_ITEMS
        .filter((m) => m.roles.includes(user.role))
        .map((m) => {
            const file = m.href.split('/').pop();
            const active =
                here === file ||
                (m.key === 'dashboard' && isIndexLike);
            return `<li><a href="${m.href}" class="sidebar__item${active ? ' sidebar__item--active' : ''}"><span class="sidebar__item-icon">${m.icon}</span>${escapeHtml(m.label)}</a></li>`;
        })
        .join('');

    root.innerHTML = `
        <div class="sidebar__brand">
            <div class="sidebar__brand-icon">⚙️</div>
            <span>FitHub</span>
        </div>
        <div class="sidebar__section-label">主功能</div>
        <ul class="sidebar__menu">${itemsHtml}</ul>
        <div class="sidebar__divider"></div>
        <ul class="sidebar__menu">
            <li><a href="/c/" class="sidebar__item"><span class="sidebar__item-icon">🏋️</span>返回 C 端</a></li>
        </ul>
    `;
    return user;
}

export function renderUserBadge(user) {
    if (!user) return;
    const nameEl = document.getElementById('userName');
    const roleEl = document.getElementById('userRole');
    if (nameEl) nameEl.textContent = user.nickname || user.username;
    if (roleEl) roleEl.textContent = ROLE_LABEL[user.role] || user.role;
}

export function bindLogout() {
    const btn = document.getElementById('logoutBtn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        if (!confirm('确定退出？')) return;
        ['fithub_admin_access', 'fithub_admin_refresh', 'fithub_admin_user'].forEach((k) =>
            localStorage.removeItem(k),
        );
        window.location.href = '/admin/login.html';
    });
}

// 按角色隐藏带 data-requires-roles 的元素（页面内剩余的细粒度过滤）
export function applyRoleVisibility(user) {
    if (!user) return;
    document.querySelectorAll('[data-requires-roles]').forEach((el) => {
        const allowed = el.dataset.requiresRoles.split(',');
        if (!allowed.includes(user.role)) el.style.display = 'none';
    });
}

// —— 自动挂载 ——
function autoMount() {
    const user = renderSidebar();
    renderUserBadge(user);
    bindLogout();
    applyRoleVisibility(user);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
} else {
    autoMount();
}
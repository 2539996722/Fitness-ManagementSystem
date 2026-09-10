/**
 * B 端评论管理（M7，PRD §5.2 + §9.6）。
 *
 * 功能：
 *   - 列出全部评论（默认 status=0；勾选"含已删除"含 status=1）
 *   - 按动作 ID / 用户 ID / 关键词筛选
 *   - 删除评论（强删：UPDATE status=1）
 *
 * 用法：reviews.html 内 `<section id="root"></section>` + 本文件。
 */

const TOKEN_KEY = 'fithub_admin_access';
const USER_KEY = 'fithub_admin_user';

const state = {
    filters: { exercise_id: '', user_id: '', keyword: '', include_deleted: false },
    limit: 50,
    offset: 0,
    total: 0,
    items: [],
    loading: false,
};

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

function getUser() {
    const u = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t || !u) {
        window.location.href = '/admin/login.html';
        return null;
    }
    if (u.role !== 'admin') {
        alert('403 该页面仅管理员可访问');
        window.location.href = '/admin/dashboard.html';
        return null;
    }
    return u;
}

async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json' };
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`/api/v1${path}`, {
        ...options,
        headers: { ...headers, ...(options.headers || {}) },
        body: options.body ? JSON.stringify(options.body) : undefined,
    });
    if (resp.status === 401) {
        localStorage.clear();
        window.location.href = '/admin/login.html';
        throw new Error('未登录');
    }
    if (resp.status === 204) return null;
    if (!resp.ok) {
        const e = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(e.detail || '请求失败');
    }
    return resp.json();
}

function showAlert(msg, kind = 'success') {
    const el = document.getElementById('alert');
    if (!el) return;
    el.className = `alert alert--${kind}`;
    el.textContent = msg;
    el.classList.remove('alert--hidden');
    setTimeout(() => el.classList.add('alert--hidden'), 3000);
}

function renderHeader(user) {
    document.getElementById('userName').textContent = user.nickname || user.username;
    document.getElementById('userRole').textContent = '管理员';
    document.getElementById('logoutBtn').addEventListener('click', () => {
        if (!confirm('确定退出？')) return;
        localStorage.clear();
        window.location.href = '/admin/login.html';
    });
}

function renderStars(rating) {
    return `<span class="rv-rating">${'★'.repeat(rating)}${'☆'.repeat(5 - rating)}</span> <span style="color:#6b7280;font-size:12px;">${rating}/5</span>`;
}

function buildQuery() {
    const p = new URLSearchParams();
    p.set('limit', state.limit);
    p.set('offset', state.offset);
    if (state.filters.exercise_id) p.set('exercise_id', state.filters.exercise_id);
    if (state.filters.user_id) p.set('user_id', state.filters.user_id);
    if (state.filters.keyword) p.set('keyword', state.filters.keyword);
    if (state.filters.include_deleted) p.set('include_deleted', 'true');
    return p.toString();
}

async function loadReviews() {
    state.loading = true;
    const root = document.getElementById('root');
    try {
        const data = await api(`/admin/reviews?${buildQuery()}`);
        state.items = data.items || [];
        state.total = data.total || 0;
        renderList();
    } catch (e) {
        root.innerHTML = `<div class="rv-card"><div class="rv-empty" style="color:#ef4444;">加载失败：${esc(e.message)}</div></div>`;
    } finally {
        state.loading = false;
    }
}

function renderList() {
    const root = document.getElementById('root');
    root.innerHTML = `
        <div class="rv-card">
            <div class="rv-card__title">🔍 筛选条件</div>
            <div class="rv-filters">
                <div class="rv-filter">
                    <label class="rv-filter__label">动作 ID</label>
                    <input id="f-exerciseId" class="rv-input rv-input--narrow" placeholder="如 0001" value="${esc(state.filters.exercise_id)}">
                </div>
                <div class="rv-filter">
                    <label class="rv-filter__label">用户 ID</label>
                    <input id="f-userId" type="number" class="rv-input rv-input--narrow" placeholder="数字 ID" value="${esc(state.filters.user_id)}">
                </div>
                <div class="rv-filter">
                    <label class="rv-filter__label">评论关键词</label>
                    <input id="f-keyword" class="rv-input" placeholder="模糊匹配内容" value="${esc(state.filters.keyword)}">
                </div>
                <div class="rv-filter">
                    <label class="rv-checkbox">
                        <input id="f-includeDeleted" type="checkbox" ${state.filters.include_deleted ? 'checked' : ''}>
                        含已删除
                    </label>
                </div>
                <button id="btnApply" class="rv-btn rv-btn--primary">查询</button>
                <button id="btnReset" class="rv-btn">重置</button>
            </div>
        </div>

        <div class="rv-card">
            <div class="rv-card__title">📋 评论列表 <span style="font-size:13px;color:#6b7280;font-weight:400;">（共 ${state.total} 条）</span></div>
            ${state.items.length === 0 ? `<div class="rv-empty">📭 暂无评论</div>` : `
            <div class="rv-table-wrap">
                <table class="rv-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>评分</th>
                            <th>评论内容</th>
                            <th>用户</th>
                            <th>动作</th>
                            <th>时间</th>
                            <th>状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.items.map(r => `
                            <tr data-rid="${r.id}">
                                <td>#${r.id}</td>
                                <td>${renderStars(r.rating)}</td>
                                <td><div class="rv-content" title="${esc(r.content || '')}">${esc(r.content || '(无内容)')}</div></td>
                                <td>${esc(r.nickname || r.username)} <span style="color:#9ca3af;font-size:12px;">#${r.user_id}</span></td>
                                <td><a href="/c/detail.html?id=${esc(r.exercise_id)}" target="_blank" style="color:var(--color-primary);text-decoration:none;">${esc(r.exercise_name || r.exercise_id)}</a> <span style="color:#9ca3af;font-size:12px;">#${esc(r.exercise_id)}</span></td>
                                <td style="font-size:12px;color:#6b7280;">${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '—'}</td>
                                <td>${r.status === 1 ? '<span class="rv-badge rv-badge--del">已删除</span>' : '<span class="rv-badge rv-badge--ok">正常</span>'}</td>
                                <td>
                                    ${r.status === 0
                                        ? `<button class="rv-btn rv-btn--sm rv-btn--danger" data-act="delete" data-rid="${r.id}">删除</button>`
                                        : '<span style="color:#9ca3af;font-size:12px;">—</span>'}
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ${renderPagination()}
            `}
        </div>
    `;

    document.getElementById('btnApply')?.addEventListener('click', () => {
        state.filters.exercise_id = document.getElementById('f-exerciseId').value.trim();
        state.filters.user_id = document.getElementById('f-userId').value.trim();
        state.filters.keyword = document.getElementById('f-keyword').value.trim();
        state.filters.include_deleted = document.getElementById('f-includeDeleted').checked;
        state.offset = 0;
        loadReviews();
    });
    document.getElementById('btnReset')?.addEventListener('click', () => {
        state.filters = { exercise_id: '', user_id: '', keyword: '', include_deleted: false };
        state.offset = 0;
        loadReviews();
    });
    document.querySelectorAll('[data-act="delete"]').forEach(btn => {
        btn.addEventListener('click', () => deleteReview(+btn.dataset.rid));
    });
    document.querySelectorAll('[data-page]').forEach(btn => {
        btn.addEventListener('click', () => {
            state.offset = +btn.dataset.page;
            loadReviews();
        });
    });
}

function renderPagination() {
    const pageSize = state.limit;
    const curPage = Math.floor(state.offset / pageSize) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / pageSize));
    return `
        <div class="rv-pagination">
            <span>第 ${curPage} / ${totalPages} 页 · 共 ${state.total} 条</span>
            <div class="rv-pagination__btns">
                <button class="rv-btn rv-btn--sm" data-page="${Math.max(0, state.offset - pageSize)}" ${state.offset === 0 ? 'disabled' : ''}>上一页</button>
                <button class="rv-btn rv-btn--sm" data-page="${state.offset + pageSize}" ${state.offset + pageSize >= state.total ? 'disabled' : ''}>下一页</button>
            </div>
        </div>
    `;
}

async function deleteReview(id) {
    if (!confirm(`确定删除评论 #${id}？`)) return;
    try {
        await api(`/admin/reviews/${id}`, { method: 'DELETE' });
        showAlert(`已删除评论 #${id}`, 'success');
        loadReviews();
    } catch (e) {
        showAlert('删除失败：' + e.message, 'error');
    }
}

// 入口
const user = getUser();
if (user) {
    renderHeader(user);
    loadReviews();
}

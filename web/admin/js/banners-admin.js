/**
 * B 端公告管理（M9，PRD §5.2.5）。
 *
 * 功能：
 *   - 列出全部 Banner（含停用）
 *   - 新建 / 编辑 / 删除
 *   - 一键启用 / 停用
 *   - 排序权重调整
 *
 * 用法：banners.html 内 `<section id="root"></section>` + 本文件。
 */

const TOKEN_KEY = 'fithub_admin_access';
const USER_KEY = 'fithub_admin_user';

const state = {
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

function fmtTime(s) {
    if (!s) return '—';
    const d = new Date(s);
    return d.toLocaleString('zh-CN', { hour12: false });
}

// HTML datetime-local 格式：YYYY-MM-DDTHH:mm
function toLocalInput(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(v) {
    if (!v) return null;
    return new Date(v).toISOString();
}

async function loadBanners() {
    state.loading = true;
    const root = document.getElementById('root');
    try {
        state.items = await api('/admin/banners');
        renderList();
    } catch (e) {
        root.innerHTML = `<div class="bn-empty" style="color:#dc2626;">加载失败：${esc(e.message)}</div>`;
    } finally {
        state.loading = false;
    }
}

function renderList() {
    const root = document.getElementById('root');
    const activeCount = state.items.filter(b => b.is_active).length;
    root.innerHTML = `
        <div class="bn-card">
            <div class="bn-card__title">
                📋 全部公告 <span class="bn-card__title-meta">共 ${state.items.length} 条，启用 ${activeCount} 条</span>
                <button class="bn-btn bn-btn--primary" id="btnCreate">+ 新建公告</button>
            </div>
            ${state.items.length === 0
                ? `<div class="bn-empty">📭 暂无公告，点击右上角「新建公告」开始</div>`
                : `<div class="bn-table-wrap"><table class="bn-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>标题</th>
                            <th>内容</th>
                            <th>链接</th>
                            <th>排序</th>
                            <th>生效时段</th>
                            <th>状态</th>
                            <th>更新时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.items.map(b => `
                            <tr data-bid="${b.id}">
                                <td>#${b.id}</td>
                                <td><div class="bn-title" title="${esc(b.title)}">${esc(b.title)}</div></td>
                                <td><div class="bn-content" title="${esc(b.content)}">${esc(b.content)}</div></td>
                                <td>${b.link_url ? `<a href="${esc(b.link_url)}" target="_blank" class="bn-link">${esc(b.link_url.length > 24 ? b.link_url.slice(0, 24) + '…' : b.link_url)}</a>` : '<span style="color:#9ca3af;">—</span>'}</td>
                                <td><span class="bn-sort">${b.sort_order}</span></td>
                                <td style="font-size:11px;color:#6b7280;">${(b.starts_at || b.ends_at) ? `${b.starts_at ? fmtTime(b.starts_at).slice(0,16) : '不限'} ~ ${b.ends_at ? fmtTime(b.ends_at).slice(0,16) : '不限'}` : '<span style="color:#9ca3af;">不限</span>'}</td>
                                <td>${b.is_active ? '<span class="bn-badge bn-badge--active">启用</span>' : '<span class="bn-badge bn-badge--inactive">停用</span>'}</td>
                                <td style="font-size:12px;color:#6b7280;">${fmtTime(b.updated_at)}</td>
                                <td>
                                    <button class="bn-btn bn-btn--sm" data-act="edit" data-bid="${b.id}">编辑</button>
                                    <button class="bn-btn bn-btn--sm" data-act="toggle" data-bid="${b.id}">${b.is_active ? '停用' : '启用'}</button>
                                    <button class="bn-btn bn-btn--sm bn-btn--danger" data-act="delete" data-bid="${b.id}">删除</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table></div>`}
        </div>
    `;

    document.getElementById('btnCreate')?.addEventListener('click', () => openModal('create'));
    document.querySelectorAll('[data-act="edit"]').forEach(btn => {
        btn.addEventListener('click', () => openModal('edit', +btn.dataset.bid));
    });
    document.querySelectorAll('[data-act="toggle"]').forEach(btn => {
        btn.addEventListener('click', () => toggleActive(+btn.dataset.bid));
    });
    document.querySelectorAll('[data-act="delete"]').forEach(btn => {
        btn.addEventListener('click', () => deleteBanner(+btn.dataset.bid));
    });
}

function openModal(mode, id) {
    const existing = mode === 'edit' ? state.items.find(b => b.id === id) : null;
    const isEdit = mode === 'edit';

    const mask = document.createElement('div');
    mask.className = 'bn-modal-mask bn-modal-mask--open';
    mask.innerHTML = `
        <div class="bn-modal">
            <div class="bn-modal__head">
                <div class="bn-modal__title">${isEdit ? '编辑公告' : '新建公告'}</div>
                <button class="bn-modal__close" data-act="close">×</button>
            </div>
            <div class="bn-modal__body">
                <div class="bn-form-row">
                    <label class="bn-form-row__label">标题 *</label>
                    <input id="m-title" class="bn-input" maxlength="64" value="${esc(existing?.title || '')}" placeholder="一句话标题">
                </div>
                <div class="bn-form-row">
                    <label class="bn-form-row__label">内容 *</label>
                    <textarea id="m-content" maxlength="500" placeholder="Banner 正文（建议不超过 80 字）">${esc(existing?.content || '')}</textarea>
                    <div class="bn-form-row__hint">最多 500 字</div>
                </div>
                <div class="bn-form-row">
                    <label class="bn-form-row__label">跳转链接（可选）</label>
                    <input id="m-link" class="bn-input" value="${esc(existing?.link_url || '')}" placeholder="/c/plans.html 或 https://...">
                </div>
                <div class="bn-grid-2">
                    <div class="bn-form-row">
                        <label class="bn-form-row__label">排序权重（0-999）</label>
                        <input id="m-sort" class="bn-input" type="number" min="0" max="999" value="${existing?.sort_order ?? 0}">
                        <div class="bn-form-row__hint">越小越靠前</div>
                    </div>
                    <div class="bn-form-row">
                        <label class="bn-form-row__label">启用</label>
                        <label class="bn-checkbox">
                            <input id="m-active" type="checkbox" ${(existing?.is_active ?? true) ? 'checked' : ''}>
                            立即启用
                        </label>
                    </div>
                </div>
                <div class="bn-grid-2">
                    <div class="bn-form-row">
                        <label class="bn-form-row__label">生效起始（可选）</label>
                        <input id="m-starts" class="bn-input" type="datetime-local" value="${toLocalInput(existing?.starts_at)}">
                    </div>
                    <div class="bn-form-row">
                        <label class="bn-form-row__label">生效结束（可选）</label>
                        <input id="m-ends" class="bn-input" type="datetime-local" value="${toLocalInput(existing?.ends_at)}">
                    </div>
                </div>
            </div>
            <div class="bn-modal__footer">
                <button class="bn-btn" data-act="close">取消</button>
                <button class="bn-btn bn-btn--primary" data-act="save">${isEdit ? '保存' : '创建'}</button>
            </div>
        </div>
    `;
    document.body.appendChild(mask);

    const closeModal = () => mask.remove();

    mask.addEventListener('click', (e) => {
        if (e.target === mask) closeModal();
    });
    mask.querySelectorAll('[data-act="close"]').forEach(b => b.addEventListener('click', closeModal));
    mask.querySelector('[data-act="save"]').addEventListener('click', async () => {
        const title = document.getElementById('m-title').value.trim();
        const content = document.getElementById('m-content').value.trim();
        const sort_order = parseInt(document.getElementById('m-sort').value, 10) || 0;
        const is_active = document.getElementById('m-active').checked;
        const link_url = document.getElementById('m-link').value.trim() || null;
        const starts_at = fromLocalInput(document.getElementById('m-starts').value);
        const ends_at = fromLocalInput(document.getElementById('m-ends').value);

        if (!title) return showAlert('标题不能为空', 'error');
        if (!content) return showAlert('内容不能为空', 'error');

        const body = { title, content, link_url, is_active, sort_order, starts_at, ends_at };
        try {
            if (isEdit) {
                await api(`/admin/banners/${id}`, { method: 'PATCH', body });
                showAlert(`已更新 #${id}`, 'success');
            } else {
                await api('/admin/banners', { method: 'POST', body });
                showAlert('已创建', 'success');
            }
            closeModal();
            loadBanners();
        } catch (e) {
            showAlert((isEdit ? '更新' : '创建') + '失败：' + e.message, 'error');
        }
    });
}

async function toggleActive(id) {
    const b = state.items.find(x => x.id === id);
    if (!b) return;
    try {
        await api(`/admin/banners/${id}`, { method: 'PATCH', body: { is_active: !b.is_active } });
        showAlert(`已${b.is_active ? '停用' : '启用'} #${id}`, 'success');
        loadBanners();
    } catch (e) {
        showAlert('操作失败：' + e.message, 'error');
    }
}

async function deleteBanner(id) {
    const b = state.items.find(x => x.id === id);
    if (!b) return;
    if (!confirm(`确定删除公告「${b.title}」？该操作不可撤销，并会写入操作日志。`)) return;
    try {
        await api(`/admin/banners/${id}`, { method: 'DELETE' });
        showAlert(`已删除 #${id}`, 'success');
        loadBanners();
    } catch (e) {
        showAlert('删除失败：' + e.message, 'error');
    }
}

// 入口
const user = getUser();
if (user) {
    renderHeader(user);
    loadBanners();
}
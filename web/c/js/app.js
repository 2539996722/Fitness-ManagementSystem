/**
 * C 端首页逻辑（动作库）
 */

import { api, tokenStore } from './api.js';
import { t } from './translations.js';

const state = {
    page: 1,
    pageSize: 24,
    hasMore: false,
    total: 0,
    filters: {
        keyword: '',
        body_part: '',
        equipment: '',
        target: '',
    },
};

// ---------- DOM ----------
const grid = document.getElementById('exerciseGrid');
const meta = document.getElementById('resultMeta');
const loadMoreBtn = document.getElementById('loadMore');

const searchInput = document.getElementById('searchInput');
const filterBodyPart = document.getElementById('filterBodyPart');
const filterEquipment = document.getElementById('filterEquipment');
const filterTarget = document.getElementById('filterTarget');
const resetBtn = document.getElementById('resetFilters');

// 导航栏鉴权态
const navLogin = document.getElementById('navLogin');
const navRegister = document.getElementById('navRegister');
const navLogout = document.getElementById('navLogout');

// ---------- 渲染 ----------
// 数据集中的 image/gif_url 是相对路径（如 images/0001-xxx.jpg）
// 后端把它们挂载在 /static/images 和 /static/videos
// 这里统一补全为绝对路径
function resolveMediaUrl(path) {
    if (!path) return '';
    if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/')) {
        return path;
    }
    // 相对路径：images/xxx → /static/images/xxx，videos/xxx → /static/videos/xxx
    if (path.startsWith('images/')) return '/static/' + path;
    if (path.startsWith('videos/')) return '/static/' + path;
    return path;
}

function renderCard(ex) {
    const card = document.createElement('a');
    card.href = `/c/detail.html?id=${ex.id}`;
    card.className = 'card';
    // 优先尝试真实图片，加载失败再降级到 emoji 占位符
    card.innerHTML = `
        <div class="card__image-wrap">
            <img class="card__image" src="${resolveMediaUrl(ex.image)}"
                 alt="${escapeHtml(ex.name_zh || ex.name_en)}"
                 loading="lazy"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
            <div class="card__image-placeholder" style="display:none;">
                ${getBodyPartEmoji(ex.body_part)}
            </div>
        </div>
        <div class="card__body">
            <div class="card__name-zh">${escapeHtml(ex.name_zh || ex.name_en)}</div>
            <div class="card__name-en">${escapeHtml(ex.name_en)}</div>
            <div class="card__tags">
                <span class="tag">${escapeHtml(t.bodyPart(ex.body_part))}</span>
                <span class="tag">${escapeHtml(t.equipment(ex.equipment))}</span>
            </div>
            ${ex.review_count >= 5 && ex.avg_rating != null
                ? `<div class="card__rating">★ ${Number(ex.avg_rating).toFixed(1)} <span style="color:#9ca3af;font-weight:400;">(${ex.review_count})</span></div>`
                : ''}
        </div>
    `;
    return card;
}

// 身体部位 → Emoji + 配色（作为图片加载失败的降级方案）
function getBodyPartEmoji(bodyPart) {
    const map = {
        'chest':      { emoji: '💪', color: '#fee2e2' },
        'back':       { emoji: '🏋️', color: '#dbeafe' },
        'shoulders':  { emoji: '🤸', color: '#fef3c7' },
        'upper arms': { emoji: '💪', color: '#fce7f3' },
        'lower arms': { emoji: '✋', color: '#fce7f3' },
        'upper legs': { emoji: '🦵', color: '#d1fae5' },
        'lower legs': { emoji: '🦶', color: '#d1fae5' },
        'waist':      { emoji: '🧘', color: '#ede9fe' },
        'cardio':     { emoji: '🏃', color: '#ffe4e6' },
        'neck':       { emoji: '🧎', color: '#f3f4f6' },
    };
    const entry = map[bodyPart?.toLowerCase()] || { emoji: '🏃', color: '#f3f4f6' };
    return `<span style="background:${entry.color};display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:64px;">${entry.emoji}</span>`;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function renderCards(items, append = false) {
    if (!append) grid.innerHTML = '';
    if (!items.length && !append) {
        grid.innerHTML = '<div class="empty">没有符合条件的动作</div>';
        return;
    }
    items.forEach((ex) => grid.appendChild(renderCard(ex)));
}

function updateMeta() {
    meta.textContent = `共 ${state.total} 个动作`;
}

function updateLoadMore() {
    loadMoreBtn.style.display = state.hasMore ? 'inline-flex' : 'none';
}

// ---------- 鉴权 UI ----------
function updateAuthUI() {
    if (tokenStore.isLoggedIn) {
        navLogin.style.display = 'none';
        navRegister.style.display = 'none';
        navLogout.style.display = 'inline-flex';
        navLogout.textContent = `退出（${tokenStore.user?.nickname || tokenStore.user?.username || ''}）`;
    } else {
        navLogin.style.display = 'inline-flex';
        navRegister.style.display = 'inline-flex';
        navLogout.style.display = 'none';
    }
}

navLogout?.addEventListener('click', () => {
    if (confirm('确定要退出登录吗？')) {
        tokenStore.clear();
        updateAuthUI();
        window.location.reload();
    }
});

// ---------- 数据加载 ----------
async function loadFilters() {
    try {
        const opts = await api.exercises.filters();
        fillSelect(filterBodyPart, opts.body_parts);
        fillSelect(filterEquipment, opts.equipment);
        fillSelect(filterTarget, opts.targets);
    } catch (e) {
        console.warn('筛选选项加载失败:', e);
    }
}

// 筛选下拉：根据 select 元素 id 决定用哪个翻译函数
function fillSelect(select, options) {
    const translate = select.id === 'filterBodyPart' ? t.bodyPart
                    : select.id === 'filterEquipment' ? t.equipment
                    : select.id === 'filterTarget'   ? t.target
                    : (v) => v;
    options.forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v;                // 值仍是英文（用于 API 查询）
        opt.textContent = translate(v); // 显示中文
        select.appendChild(opt);
    });
}

async function loadExercises(reset = true) {
    if (reset) {
        state.page = 1;
        grid.innerHTML = '<div class="loading">加载中...</div>';
    }

    try {
        const params = {
            ...state.filters,
            page: state.page,
            page_size: state.pageSize,
        };
        const data = await api.exercises.list(params);
        state.total = data.total;
        state.hasMore = data.has_more;
        renderCards(data.items, !reset);
        updateMeta();
        updateLoadMore();
    } catch (e) {
        grid.innerHTML = `<div class="empty">❌ 加载失败：${e.message}<br><br>请确认服务已启动（访问 <a href="/api/v1/health">/api/v1/health</a> 验证）</div>`;
        console.error(e);
    }
}

// ---------- 事件 ----------
let searchTimer = null;
searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        state.filters.keyword = e.target.value.trim();
        loadExercises();
    }, 300);
});

filterBodyPart.addEventListener('change', (e) => {
    state.filters.body_part = e.target.value;
    loadExercises();
});

filterEquipment.addEventListener('change', (e) => {
    state.filters.equipment = e.target.value;
    loadExercises();
});

filterTarget.addEventListener('change', (e) => {
    state.filters.target = e.target.value;
    loadExercises();
});

resetBtn.addEventListener('click', () => {
    searchInput.value = '';
    filterBodyPart.value = '';
    filterEquipment.value = '';
    filterTarget.value = '';
    state.filters = { keyword: '', body_part: '', equipment: '', target: '' };
    loadExercises();
});

loadMoreBtn.addEventListener('click', () => {
    state.page++;
    loadExercises(false);
});

// ---------- 启动 ----------
updateAuthUI();
loadFilters();
loadExercises();

// ---------- 鼠标聚光灯：事件委托到 grid 容器 ----------
grid.addEventListener('mousemove', (e) => {
    const card = e.target.closest('.card');
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    card.style.setProperty('--mouse-x', `${x}%`);
    card.style.setProperty('--mouse-y', `${y}%`);
});
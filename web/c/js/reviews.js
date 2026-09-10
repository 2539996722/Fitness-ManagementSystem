/**
 * 动作评论模块（M7）
 *
 * 用法：
 *   import { mountReviews } from './reviews.js';
 *   mountReviews('reviewsMount', { exerciseId: '0001', onLoaded: (stats) => {} });
 *
 * 功能：
 *   - 顶部：评分概览（≥5 条评论才显示 avg）
 *   - 中部：当前用户的打分/评论表单（未登录则提示登录）
 *   - 列表：分页 10/页，可"加载更多"
 *   - 自己评论的列表项可"修改/删除"
 *
 * ponytail: 状态机用模块级变量，组件小到一个页面只会 mount 一次，没必要
 * 走 props/observable。评分变化后通过 onLoaded 回调把新的 stats 抛出去，
 * 头部概览由 detail.html 自己更新。
 */

import { api, tokenStore } from './api.js';

const PAGE_SIZE = 10;

export async function mountReviews(rootId, { exerciseId, onLoaded } = {}) {
    const root = document.getElementById(rootId);
    if (!root) return;

    if (!exerciseId) {
        root.innerHTML = '';
        return;
    }

    // ===== 内部状态 =====
    let myReview = null;     // 当前用户已存在的评论（编辑态初始值）
    let rating = 0;          // 表单中选中的星数
    let content = '';        // 表单中的文本
    let reviews = [];        // 当前页评论列表
    let page = 1;
    let total = 0;
    let hasMore = false;
    let loading = false;
    let editing = false;     // 是否正在编辑（区分新建 vs 修改）

    // ===== 渲染 =====
    function render() {
        root.innerHTML = `
            <section class="rv-section">
                <h2 class="rv-section__title">
                    💬 评分与评论
                    <span class="rv-summary" id="rvSummary"></span>
                </h2>

                <div id="rvError" class="rv-error" style="display:none;"></div>

                <div id="rvFormHost"></div>

                <div id="rvList" class="rv-list"></div>
                <div id="rvLoadMore" class="rv-loadmore"></div>
            </section>
        `;
        renderSummary();
        renderForm();
        renderList();
        bindEvents();
    }

    function renderSummary() {
        const el = document.getElementById('rvSummary');
        if (!el) return;
        // avg 由后端保证：count >= 5 才有 avg_rating
        if (total >= 5) {
            const avg = (window._rvAvgRating || 0).toFixed(1);
            el.innerHTML = `<span class="rv-stars">★</span> <strong>${avg}</strong> · ${total} 条评论`;
            el.style.display = 'inline-flex';
        } else if (total > 0) {
            el.innerHTML = `${total} 条评论 · 满 5 条后显示评分`;
            el.style.display = 'inline-flex';
        } else {
            el.style.display = 'none';
        }
    }

    function renderForm() {
        const host = document.getElementById('rvFormHost');
        if (!host) return;

        if (!tokenStore.isLoggedIn) {
            const next = encodeURIComponent(location.pathname + location.search);
            host.innerHTML = `
                <div class="rv-please-login">
                    <a href="/c/login.html?next=${next}">登录</a>
                    后即可打分和评论
                </div>
            `;
            return;
        }

        // 初始值（如果已加载过 myReview）
        const initRating = myReview?.rating || 0;
        const initContent = myReview?.content || '';

        host.innerHTML = `
            <div class="rv-form">
                <div class="rv-form__row">
                    <span class="rv-form__label">你的评分</span>
                    <div class="rv-form__stars" id="rvStars">
                        ${[1, 2, 3, 4, 5].map((n) =>
                            `<span class="rv-form__star ${n <= (rating || initRating) ? 'rv-form__star--on' : ''}"
                                  data-value="${n}">★</span>`
                        ).join('')}
                    </div>
                    <span class="rv-form__hint" id="rvRatingHint">
                        ${(rating || initRating) ? `已选 ${rating || initRating} 星` : '点击星星评分'}
                    </span>
                </div>
                <div class="rv-form__row" style="align-items:flex-start;">
                    <span class="rv-form__label" style="padding-top:8px;">评论</span>
                    <div style="flex:1;">
                        <textarea class="rv-form__textarea"
                                  id="rvContent"
                                  maxlength="500"
                                  placeholder="说说你的训练感受（选填，≤500 字）">${escapeHtml(content || initContent)}</textarea>
                        <div class="rv-form__counter" id="rvCounter">
                            ${(content || initContent).length} / 500
                        </div>
                    </div>
                </div>
                <div class="rv-form__actions">
                    ${myReview ? `
                        <button class="rv-btn rv-btn--ghost rv-btn--danger" id="rvCancelEdit">取消编辑</button>
                    ` : ''}
                    <button class="rv-btn rv-btn--primary" id="rvSubmit"
                            ${!(rating || initRating) ? 'disabled' : ''}>
                        ${myReview ? '💾 保存修改' : '📝 提交评论'}
                    </button>
                </div>
            </div>
        `;

        // 绑定星 + 文本输入
        document.querySelectorAll('#rvStars .rv-form__star').forEach((star) => {
            star.addEventListener('click', () => {
                rating = parseInt(star.dataset.value, 10);
                editing = true;
                renderForm();
                renderSummary();
            });
            star.addEventListener('mouseenter', () => {
                const v = parseInt(star.dataset.value, 10);
                document.querySelectorAll('#rvStars .rv-form__star').forEach((s) => {
                    const n = parseInt(s.dataset.value, 10);
                    s.classList.toggle('rv-form__star--on', n <= v);
                });
            });
        });
        const starsHost = document.getElementById('rvStars');
        if (starsHost) {
            starsHost.addEventListener('mouseleave', () => {
                document.querySelectorAll('#rvStars .rv-form__star').forEach((s) => {
                    const n = parseInt(s.dataset.value, 10);
                    s.classList.toggle('rv-form__star--on', n <= rating);
                });
            });
        }

        const ta = document.getElementById('rvContent');
        const counter = document.getElementById('rvCounter');
        if (ta) {
            ta.addEventListener('input', () => {
                content = ta.value;
                editing = true;
                counter.textContent = `${content.length} / 500`;
                counter.classList.toggle('rv-form__counter--warn', content.length >= 450);
            });
        }

        const submitBtn = document.getElementById('rvSubmit');
        if (submitBtn) submitBtn.addEventListener('click', submitReview);

        const cancelBtn = document.getElementById('rvCancelEdit');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                rating = myReview?.rating || 0;
                content = myReview?.content || '';
                editing = false;
                renderForm();
            });
        }
    }

    function renderList() {
        const host = document.getElementById('rvList');
        if (!host) return;

        if (loading && reviews.length === 0) {
            host.innerHTML = '<div class="rv-loading">加载中...</div>';
            return;
        }
        if (reviews.length === 0) {
            host.innerHTML = `<div class="rv-empty">还没有评论，来抢第一条沙发吧 🎉</div>`;
            const lm = document.getElementById('rvLoadMore');
            if (lm) lm.innerHTML = '';
            return;
        }

        host.innerHTML = reviews.map((r) => `
            <div class="rv-item" data-id="${r.id}">
                <div class="rv-item__head">
                    <div>
                        <span class="rv-item__author">${escapeHtml(r.author?.nickname || '匿名用户')}</span>
                        ${r.is_mine ? '<span class="rv-item__mine-tag">我</span>' : ''}
                    </div>
                    <span class="rv-item__date">${formatDate(r.created_at)}${r.updated_at && r.updated_at !== r.created_at ? ' · 已编辑' : ''}</span>
                </div>
                <div class="rv-item__rating">${'★'.repeat(r.rating)}${'☆'.repeat(5 - r.rating)}</div>
                ${r.content ? `<div class="rv-item__content">${escapeHtml(r.content)}</div>` : ''}
                ${r.is_mine ? `
                    <div class="rv-item__actions">
                        <button class="rv-link-btn rv-link-btn--edit">✏️ 编辑</button>
                        <button class="rv-link-btn rv-link-btn--danger">🗑 删除</button>
                    </div>
                ` : ''}
            </div>
        `).join('');

        // 绑定自己评论的编辑/删除
        host.querySelectorAll('.rv-item').forEach((el) => {
            const id = parseInt(el.dataset.id, 10);
            const editBtn = el.querySelector('.rv-link-btn--edit');
            const delBtn = el.querySelector('.rv-link-btn--danger');
            if (editBtn) editBtn.addEventListener('click', () => editMine(id));
            if (delBtn) delBtn.addEventListener('click', () => deleteMine(id));
        });

        const lm = document.getElementById('rvLoadMore');
        if (lm) {
            if (loading) {
                lm.innerHTML = '<button class="rv-btn" disabled>加载中...</button>';
            } else if (hasMore) {
                lm.innerHTML = '<button class="rv-btn" id="rvLoadMoreBtn">加载更多</button>';
                const btn = document.getElementById('rvLoadMoreBtn');
                if (btn) btn.addEventListener('click', loadMore);
            } else if (reviews.length > PAGE_SIZE) {
                lm.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">已加载全部</span>';
            } else {
                lm.innerHTML = '';
            }
        }
    }

    function bindEvents() {
        // render 完成后由 renderForm/renderList 自行绑定局部事件
    }

    // ===== 数据加载 =====

    async function loadFirst() {
        loading = true;
        reviews = [];
        page = 1;
        try {
            const data = await api.get(`/exercises/${exerciseId}/reviews?page=1&page_size=${PAGE_SIZE}`);
            reviews = data.items;
            total = data.total;
            hasMore = data.has_more;
            // 找到自己的评论（如果有）
            const me = tokenStore.user?.id;
            myReview = reviews.find((r) => r.is_mine) || null;
            // 自己评论如果不在第一页，尝试拉后续页找
            if (!myReview && me) {
                for (let p = 2; p <= Math.ceil(total / PAGE_SIZE); p++) {
                    const next = await api.get(`/exercises/${exerciseId}/reviews?page=${p}&page_size=${PAGE_SIZE}`);
                    myReview = next.items.find((r) => r.is_mine) || null;
                    if (myReview) break;
                }
            }
            // 评分概览（avg_rating）从 exercise detail 接口拿更稳
            await refreshAvgRating();
        } catch (e) {
            showError('加载评论失败：' + e.message);
        } finally {
            loading = false;
            render();
            if (onLoaded) onLoaded({ total, avg: window._rvAvgRating });
        }
    }

    async function loadMore() {
        if (loading || !hasMore) return;
        loading = true;
        renderList();
        try {
            const next = page + 1;
            const data = await api.get(`/exercises/${exerciseId}/reviews?page=${next}&page_size=${PAGE_SIZE}`);
            reviews = reviews.concat(data.items);
            page = next;
            hasMore = data.has_more;
        } catch (e) {
            showError('加载更多失败：' + e.message);
        } finally {
            loading = false;
            renderList();
        }
    }

    async function refreshAvgRating() {
        try {
            const ex = await api.get(`/exercises/${exerciseId}`);
            window._rvAvgRating = ex.avg_rating;
        } catch {
            window._rvAvgRating = null;
        }
    }

    // ===== 操作 =====
    async function submitReview() {
        const finalRating = rating || myReview?.rating || 0;
        const finalContent = document.getElementById('rvContent')?.value ?? '';
        if (!finalRating) {
            showError('请先打分（1-5 星）');
            return;
        }
        if (finalContent.length > 500) {
            showError('评论不能超过 500 字');
            return;
        }
        hideError();
        try {
            const r = await api.post(`/exercises/${exerciseId}/reviews`, {
                rating: finalRating,
                content: finalContent.trim() || null,
            });
            myReview = r;
            rating = r.rating;
            content = r.content || '';
            editing = false;
            await loadFirst();
        } catch (e) {
            showError(e.message || '提交失败');
        }
    }

    function editMine(id) {
        const target = reviews.find((r) => r.id === id);
        if (!target) return;
        rating = target.rating;
        content = target.content || '';
        editing = true;
        // 滚到表单
        document.getElementById('rvFormHost')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        renderForm();
    }

    async function deleteMine(id) {
        if (!confirm('确定删除这条评论？')) return;
        try {
            await api.delete(`/exercises/${exerciseId}/reviews/${id}`);
            if (myReview?.id === id) {
                myReview = null;
                rating = 0;
                content = '';
            }
            await loadFirst();
        } catch (e) {
            showError('删除失败：' + e.message);
        }
    }

    // ===== helpers =====
    function showError(msg) {
        const el = document.getElementById('rvError');
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }
    function hideError() {
        const el = document.getElementById('rvError');
        if (el) el.style.display = 'none';
    }

    // 启动
    await loadFirst();
}

// ===== utility =====
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        const now = new Date();
        const diffMs = now - d;
        const day = 24 * 60 * 60 * 1000;
        if (diffMs < day) {
            const h = Math.floor(diffMs / 3600000);
            const m = Math.floor((diffMs % 3600000) / 60000);
            if (h > 0) return `${h} 小时前`;
            if (m > 0) return `${m} 分钟前`;
            return '刚刚';
        }
        if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前`;
        return d.toLocaleDateString('zh-CN');
    } catch {
        return iso;
    }
}

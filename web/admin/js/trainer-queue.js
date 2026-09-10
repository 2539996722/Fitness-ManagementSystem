/**
 * 教练工作台模块（M8）。
 *
 * 用法：
 *   <section id="trainerPanel"></section>
 *   <script type="module">
 *     import { mountTrainer } from './js/trainer-queue.js';
 *     mountTrainer('trainerPanel');
 *   </script>
 *
 * 复用 queue.js 的 qp-* CSS 类（队列 + 聊天 + 用户卡 + 提示词）。
 * 与客服的差异：多了"推荐模板"、"定制计划"、"提示词推荐"三块。
 */

const TOKEN_KEY = 'fithub_admin_access';
const USER_KEY = 'fithub_admin_user';

// ponytail: 教练常用话术模板。点一下填进输入框。MVP 用前端常量,
// 后续上 SystemConfig 持久化时把这里改成从 /admin/system-config 拉。
const TRAINER_PROMPTS = [
    { icon: '🎯', title: '询问训练目标', text: '您好，我是您的专属教练。请问您目前主要的训练目标是什么？增肌、减脂还是塑形？' },
    { icon: '🏋️', title: '推荐训练计划', text: '根据您最近的身体数据，我为您推荐一套训练计划。先从基础动作开始，每周 3-4 次，每次 60-90 分钟，您看可以吗？' },
    { icon: '📐', title: '动作要点指导', text: '做这个动作时请注意：保持背部挺直、核心收紧、动作全程保持节奏控制。宁可轻一点也要把动作做对，避免受伤。' },
    { icon: '🤔', title: '询问训练反馈', text: '您今天的训练感受如何？有没有哪个动作感觉特别吃力或不适？训练后的肌肉酸痛程度怎么样？' },
    { icon: '💡', title: '训练建议', text: '根据您最近一周的训练数据，我建议您：\n1. 保证充足睡眠（7-8 小时）\n2. 训练后 30 分钟内补充蛋白质\n3. 下次训练前做好热身' },
    { icon: '🍎', title: '饮食建议', text: '训练效果 70% 来自饮食。请问您目前的饮食习惯是怎样的？建议每天蛋白质摄入量 = 体重(kg) × 1.6-2.2g。' },
    { icon: '😴', title: '询问恢复状态', text: '训练后的恢复非常重要。请问您昨晚的睡眠质量如何？身体有没有持续酸痛或不适感？' },
    { icon: '🎉', title: '鼓励用户', text: '坚持就是胜利！您已经完成了多次训练，离目标越来越近了。不要追求完美，追求持续。我们一起加油！' },
];

const HTML = `
<div class="qp-card">
  <div class="qp-toolbar">
    <div class="qp-tabs">
      <button class="qp-tab qp-tab--active" data-tab="queue">📥 待接入</button>
      <button class="qp-tab" data-tab="history">📜 我的咨询</button>
    </div>
    <button class="qp-btn qp-btn--ghost" id="q-btnRefresh">🔄 刷新</button>
  </div>
  <div class="qp-grid">
    <section class="qp-pane qp-pane--list">
      <div class="qp-list" id="q-queueList">
        <div class="qp-empty">加载中...</div>
      </div>
    </section>

    <section class="qp-pane qp-chat">
      <div class="qp-chat__head">
        <div class="qp-chat__head-left">
          <div class="qp-chat__title" id="q-chatTitle">请选择会话</div>
          <div class="qp-chat__sub" id="q-chatSub">左侧选一个会话开始</div>
        </div>
        <div class="qp-chat__actions">
          <button class="qp-btn qp-btn--claim" id="q-btnClaim" disabled>接入</button>
          <button class="qp-btn qp-btn--accent" id="q-btnReco" disabled title="向会员推荐模板">📋 模板</button>
          <button class="qp-btn qp-btn--accent" id="q-btnCustom" disabled title="基于模板为会员定制计划">⚡ 定制</button>
          <button class="qp-btn qp-btn--close" id="q-btnClose" disabled>结束</button>
        </div>
      </div>
      <div class="qp-chat__status" id="q-chatStatusBar" style="display: none;"></div>
      <div class="qp-chat__msgs" id="q-chatMessages">
        <div class="qp-empty">左侧选一个会话开始</div>
      </div>
      <div class="qp-chat__input">
        <textarea id="q-msgInput" rows="2" placeholder="输入回复，Ctrl+Enter 发送..." disabled></textarea>
        <button class="qp-btn-send" id="q-btnSend" disabled>发送</button>
      </div>
    </section>

    <aside class="qp-pane qp-pane--user">
      <div class="qp-user-pane__head">👤 会员信息</div>
      <div id="q-userCard" class="qp-user-card">
        <div class="qp-user-card__empty">选择会话后展示</div>
      </div>
      <div class="qp-prompts__head">💡 提示词推荐</div>
      <div class="qp-prompts__list" id="q-promptsList">
        <div class="qp-prompts__empty">选择会话后展示</div>
      </div>
      <div class="qp-user-pane__footer">
        <button class="qp-btn qp-btn--ghost" id="q-btnTemplates" style="width:100%;justify-content:center;">📚 浏览我的模板</button>
      </div>
    </aside>
  </div>
</div>

<!-- 模板选择 modal -->
<div id="q-tplModal" class="qp-modal" style="display:none;">
  <div class="qp-modal__backdrop"></div>
  <div class="qp-modal__panel">
    <div class="qp-modal__head">
      <span id="q-tplModalTitle">选择模板</span>
      <button id="q-tplModalClose">×</button>
    </div>
    <div class="qp-modal__body" id="q-tplModalBody">
      <div class="qp-empty">加载中...</div>
    </div>
  </div>
</div>
`;

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

export function mountTrainer(rootId) {
    const root = document.getElementById(rootId);
    if (!root) return;
    // ponytail: 与 queue.js 共享 q- 前缀的 ID/class，必须限定到 root 子树，
    // 否则 document.getElementById 会取到 csPanel 的元素，导致 trainer 视图永远渲染在不可见区。
    const $ = (sel) => root.querySelector(sel);
    const $$ = (sel) => root.querySelectorAll(sel);
    root.innerHTML = HTML;

    const user = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    if (!localStorage.getItem(TOKEN_KEY) || !user) {
        root.innerHTML = '<div class="qp-empty">未登录</div>';
        return;
    }
    if (!['trainer', 'admin'].includes(user.role)) {
        root.innerHTML = '<div class="qp-empty" style="color:#ef4444;">403 无权访问</div>';
        return;
    }

    const api = {
        async request(path, options = {}) {
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
            if (!resp.ok) {
                const e = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(e.detail || '请求失败');
            }
            if (resp.status === 204) return null;
            return resp.json();
        },
        get: (p) => api.request(p),
        post: (p, b) => api.request(p, { method: 'POST', body: b }),
    };

    const state = {
        tab: 'queue',  // queue | history
        queue: [],
        history: [],
        currentConvId: null,
        currentConv: null,
        messages: [],
        sending: false,
        currentConvStatus: null,
        sseAbort: null,
        templatesCache: null,
    };

    // ============ Tab 切换 ============
    $$('.qp-tab').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    function switchTab(tab) {
        if (state.tab === tab) return;
        state.tab = tab;
        $$('.qp-tab').forEach(b => {
            b.classList.toggle('qp-tab--active', b.dataset.tab === tab);
        });
        if (tab === 'queue') {
            renderQueue();
        } else {
            loadHistory();
        }
    }

    // ============ 待接入队列 ============
    async function loadQueue() {
        const wrap = $('#q-queueList');
        try {
            const data = await api.get('/trainer/queue');
            state.queue = data.items || [];
            renderQueue();
        } catch (e) {
            console.error('队列加载失败:', e);
            if (wrap) wrap.innerHTML = `<div class="qp-empty" style="color:#ef4444;">加载失败：${esc(e.message)}</div>`;
        }
    }

    function renderQueue() {
        const wrap = $('#q-queueList');
        if (!wrap) return;
        if (!state.queue.length) {
            wrap.innerHTML = '<div class="qp-empty">📭 暂无待接入</div>';
            return;
        }
        wrap.innerHTML = state.queue.map(c => {
            const waitMin = Math.floor((Date.now() - new Date(c.waiting_since || c.updated_at).getTime()) / 60000);
            const wait = waitMin < 1 ? '刚刚' : `${waitMin} 分钟`;
            return `
                <div class="qp-queue-item ${c.conversation_id === state.currentConvId ? 'qp-queue-item--active' : ''}" data-cid="${c.conversation_id}" data-from="queue">
                    <div class="qp-queue-item__title">${esc(c.nickname || c.username)} <span style="font-weight:400;color:#6b7280;font-size:12px;">· ${esc(c.title)}</span></div>
                    <div class="qp-queue-item__meta">等待 ${wait} · 会话 #${c.conversation_id}</div>
                    <div class="qp-queue-item__preview">${esc(c.last_message || '—')}</div>
                </div>
            `;
        }).join('');
        wrap.querySelectorAll('[data-from="queue"]').forEach(el => {
            el.addEventListener('click', () => selectQueueConversation(+el.dataset.cid));
        });
    }

    $('#q-btnRefresh').addEventListener('click', loadQueue);
    setInterval(() => { if (state.tab === 'queue') loadQueue(); }, 5000);
    loadQueue();

    // ============ 我的咨询（历史） ============
    async function loadHistory() {
        try {
            const data = await api.get('/trainer/conversations/history');
            state.history = data.items || [];
            renderHistory();
        } catch (e) {
            console.error('历史加载失败:', e);
            const wrap = $('#q-queueList');
            if (wrap) wrap.innerHTML = `<div class="qp-empty" style="color:#ef4444;">加载失败：${esc(e.message)}</div>`;
        }
    }

    function renderHistory() {
        const wrap = $('#q-queueList');
        if (!wrap) return;
        if (!state.history.length) {
            wrap.innerHTML = '<div class="qp-empty">📭 暂无历史会话</div>';
            return;
        }
        const statusLabel = { ai_active: '已转回 AI', trainer_active: '咨询中', closed: '已结束' };
        wrap.innerHTML = state.history.map(c => {
            const time = c.updated_at ? new Date(c.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
            return `
                <div class="qp-queue-item" data-cid="${c.conversation_id}" data-from="history">
                    <div class="qp-queue-item__title">${esc(c.nickname || c.username)} <span style="font-weight:400;color:#6b7280;font-size:12px;">· ${esc(statusLabel[c.status] || c.status)}</span></div>
                    <div class="qp-queue-item__meta">#${c.conversation_id} · ${time}</div>
                    <div class="qp-queue-item__preview">${esc(c.last_message || '—')}</div>
                </div>
            `;
        }).join('');
        wrap.querySelectorAll('[data-from="history"]').forEach(el => {
            el.addEventListener('click', () => selectHistoryConversation(+el.dataset.cid));
        });
    }

    async function selectHistoryConversation(convId) {
        stopSSE();
        const c = state.history.find(x => x.conversation_id === convId);
        state.currentConvId = convId;
        state.currentConv = c ? {
            id: c.conversation_id, user_id: c.user_id,
            username: c.username, nickname: c.nickname, title: c.title,
            status: c.status,
        } : { id: convId };
        $('#q-chatTitle').textContent = c?.nickname || c?.username || `会话 #${convId}`;
        $('#q-chatSub').textContent = '📜 历史会话（只读）';
        renderUserCard();
        renderPrompts();
        try {
            state.messages = await api.get(`/trainer/conversations/${convId}/messages`);
            renderMessages();
        } catch (e) {
            console.error('历史消息加载失败:', e);
        }
        // 历史会话只读：禁用输入和所有动作
        applyStatus('closed');
    }

    // ============ 选中会话 ============
    async function selectQueueConversation(convId) {
        if (state.currentConvId !== convId) stopSSE();
        state.currentConvId = convId;
        const qi = state.queue.find(c => c.conversation_id === convId);
        if (qi) {
            state.currentConv = {
                id: qi.conversation_id, user_id: qi.user_id,
                username: qi.username, nickname: qi.nickname, title: qi.title,
                status: qi.status,
            };
        }
        renderQueue();
        $('#q-chatTitle').textContent =
            state.currentConv?.nickname || state.currentConv?.username || `会话 #${convId}`;
        $('#q-chatSub').textContent = state.currentConv?.title || '—';
        renderUserCard();
        renderPrompts();
        try {
            state.messages = await api.get(`/trainer/conversations/${convId}/messages`);
            renderMessages();
        } catch (e) {
            console.error('消息加载失败:', e);
        }
        applyInitialStatus(qi?.status || 'waiting_trainer');
        startSSE();
    }

    function applyInitialStatus(status) {
        applyStatus(status || 'waiting_trainer');
    }

    function applyStatus(status, opts = {}) {
        state.currentConvStatus = status;
        const bar = $('#q-chatStatusBar');
        const btnClaim = $('#q-btnClaim');
        const btnClose = $('#q-btnClose');
        const btnReco = $('#q-btnReco');
        const btnCustom = $('#q-btnCustom');
        const msgInput = $('#q-msgInput');
        const btnSend = $('#q-btnSend');

        if (status === 'waiting_trainer') {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--waiting';
            bar.textContent = '🟡 等待接入';
            btnClaim.disabled = false; btnClose.disabled = true;
            btnReco.disabled = true; btnCustom.disabled = true;
            msgInput.disabled = true; btnSend.disabled = true;
        } else if (status === 'trainer_active') {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--human';
            bar.textContent = '🟢 你正在为该会员提供教练咨询';
            btnClaim.disabled = true; btnClose.disabled = false;
            btnReco.disabled = false; btnCustom.disabled = false;
            msgInput.disabled = false; btnSend.disabled = !msgInput.value.trim() || state.sending;
        } else {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--closed';
            bar.textContent = '✅ 已结束，会话已转回 AI 教练';
            btnClaim.disabled = true; btnClose.disabled = true;
            btnReco.disabled = true; btnCustom.disabled = true;
            msgInput.disabled = true; btnSend.disabled = true;
        }
        // 提示词是否可点 = 是否有会话 + 输入框未禁用
        if (typeof syncPromptsEnabled === 'function') syncPromptsEnabled();
    }

    function renderMessages() {
        const wrap = $('#q-chatMessages');
        if (!wrap) return;
        if (!state.messages.length) {
            wrap.innerHTML = '<div class="qp-empty">暂无消息</div>';
            return;
        }
        wrap.innerHTML = state.messages.map(renderMsgHTML).join('');
        wrap.scrollTop = wrap.scrollHeight;
    }

    function renderMsgHTML(m) {
        const time = new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        if (m.sender_type === 'trainer') {
            // 教练自己发的消息 → 右侧（绿气泡）
            return renderChatBubble({ side: 'right', avatar: '教练', name: '', text: m.content, time, kind: 'trainer' });
        }
        // 推荐模板 / 定制计划卡片
        if (m.sender_type === 'trainer' && m.extra?.kind === 'recommend_template') {
            return renderTemplateCard(m, time);
        }
        if (m.sender_type === 'trainer' && m.extra?.kind === 'customize_plan') {
            return renderPlanCard(m, time);
        }
        // 会员消息 / AI 消息
        const avatar = m.sender_type === 'ai' ? 'AI' : '会员';
        return renderChatBubble({ side: 'left', avatar, name: '', text: m.content, time, kind: m.sender_type });
    }

    function renderChatBubble({ side, avatar, text, time }) {
        const safe = esc(text);
        if (side === 'right') {
            return `
                <div class="qp-msg qp-msg--customer_service" style="flex-direction: row-reverse;">
                    <div class="qp-msg__avatar" style="background: linear-gradient(135deg, #4eecc8, #10b981);">${esc(avatar)}</div>
                    <div>
                        <div class="qp-msg__bubble" style="background: #dcfce7;">${safe}</div>
                        <div class="qp-msg__time" style="text-align:right;">${time}</div>
                    </div>
                </div>
            `;
        }
        return `
            <div class="qp-msg qp-msg--user">
                <div class="qp-msg__avatar">${esc(avatar)}</div>
                <div>
                    <div class="qp-msg__bubble">${safe}</div>
                    <div class="qp-msg__time">${time}</div>
                </div>
            </div>
        `;
    }

    function renderTemplateCard(m, time) {
        const t = m.extra.template;
        return `
            <div class="qp-msg qp-msg--customer_service" style="flex-direction: row-reverse;">
                <div class="qp-msg__avatar" style="background: linear-gradient(135deg, #4eecc8, #10b981);">教练</div>
                <div>
                    <div class="qp-msg__bubble" style="background:#f0fdf4;border:1px solid #86efac;padding:12px;max-width:280px;">
                        <div style="font-weight:600;margin-bottom:4px;">📋 推荐训练模板</div>
                        ${t.cover_url ? `<img src="${esc(t.cover_url)}" style="width:100%;max-height:120px;object-fit:cover;border-radius:6px;margin-bottom:6px;">` : ''}
                        <div style="font-size:14px;font-weight:500;">${esc(t.name)}</div>
                        <div style="font-size:12px;color:#6b7280;margin:4px 0;">${esc(t.description || '')}</div>
                        <div style="font-size:11px;color:#9ca3af;">${esc(t.goal)} · ${esc(t.level)}</div>
                        <a href="/c/template-detail.html?id=${t.id}" target="_blank" style="display:inline-block;margin-top:8px;padding:4px 12px;background:#10b981;color:white;text-decoration:none;border-radius:4px;font-size:12px;">查看详情 →</a>
                    </div>
                    <div class="qp-msg__time" style="text-align:right;">${time}</div>
                </div>
            </div>
        `;
    }

    function renderPlanCard(m, time) {
        return `
            <div class="qp-msg qp-msg--customer_service" style="flex-direction: row-reverse;">
                <div class="qp-msg__avatar" style="background: linear-gradient(135deg, #4eecc8, #10b981);">教练</div>
                <div>
                    <div class="qp-msg__bubble" style="background:#eff6ff;border:1px solid #93c5fd;padding:12px;max-width:280px;">
                        <div style="font-weight:600;margin-bottom:4px;">⚡ 教练为你定制了训练计划</div>
                        <div style="font-size:13px;color:#374151;">${esc(m.content)}</div>
                        <div style="font-size:11px;color:#9ca3af;margin-top:4px;">计划 ID: #${m.extra?.plan_id}</div>
                    </div>
                    <div class="qp-msg__time" style="text-align:right;">${time}</div>
                </div>
            </div>
        `;
    }

    function appendMsg(m) {
        const wrap = $('#q-chatMessages');
        const empty = wrap.querySelector('.qp-empty');
        if (empty && empty.textContent.includes('暂无消息')) empty.remove();
        const tmp = document.createElement('div');
        tmp.innerHTML = renderMsgHTML(m);
        const el = tmp.firstElementChild;
        if (el) {
            wrap.appendChild(el);
            wrap.scrollTop = wrap.scrollHeight;
        }
    }

    function renderUserCard() {
        const wrap = $('#q-userCard');
        const c = state.currentConv;
        if (!c) { wrap.innerHTML = '<div class="qp-user-card__empty">选择会话后展示</div>'; return; }
        wrap.innerHTML = `
            <div class="qp-user-card__row"><span>用户 ID</span><span>#${c.user_id}</span></div>
            <div class="qp-user-card__row"><span>账号</span><span>${esc(c.username || '—')}</span></div>
            <div class="qp-user-card__row"><span>昵称</span><span>${esc(c.nickname || '—')}</span></div>
            <div class="qp-user-card__row"><span>会话标题</span><span>${esc(c.title || '—')}</span></div>
            <div class="qp-user-card__row"><span>会话 ID</span><span>#${c.id}</span></div>
        `;
    }

    // ============ 提示词推荐 ============
    function renderPrompts() {
        const wrap = $('#q-promptsList');
        if (!wrap) return;
        if (!state.currentConvId) {
            wrap.innerHTML = '<div class="qp-prompts__empty">选择会话后展示</div>';
            return;
        }
        wrap.innerHTML = TRAINER_PROMPTS.map((p, i) => `
            <button class="qp-prompt" type="button" data-prompt-idx="${i}" title="点击填充到输入框">
                <div class="qp-prompt__head"><span class="qp-prompt__icon">${p.icon}</span><span>${esc(p.title)}</span></div>
                <div class="qp-prompt__text">${esc(p.text)}</div>
            </button>
        `).join('');
        wrap.querySelectorAll('.qp-prompt').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = +btn.dataset.promptIdx;
                fillPrompt(TRAINER_PROMPTS[idx].text);
            });
        });
        // 同步"是否可选"状态
        syncPromptsEnabled();
    }

    // ponytail: 输入框禁用时点提示词不做事（也不报错）。
    // 已经接入了的会话里点就直接覆盖输入框内容。
    function fillPrompt(text) {
        if (!state.currentConvId) return;
        if (msgInput.disabled) return;
        msgInput.value = text;
        msgInput.focus();
        // 触发 input 事件让发送按钮按需启用
        msgInput.dispatchEvent(new Event('input'));
    }

    function syncPromptsEnabled() {
        const enabled = !!state.currentConvId && !msgInput.disabled;
        document.querySelectorAll('.qp-prompt').forEach(b => { b.disabled = !enabled; });
    }

    // ============ 接入 / 关闭 / 发送 ============
    $('#q-btnClaim').addEventListener('click', async () => {
        if (!state.currentConvId) return;
        try {
            await api.post(`/trainer/conversations/${state.currentConvId}/claim`);
            applyStatus('trainer_active');
            startSSE();
        } catch (e) { alert('接入失败：' + e.message); }
    });

    $('#q-btnClose').addEventListener('click', async () => {
        if (!state.currentConvId) return;
        if (!confirm('确定结束本次教练咨询？结束后用户可继续与 AI 对话。')) return;
        try {
            await api.post(`/trainer/conversations/${state.currentConvId}/close`);
            applyStatus('ai_active');
            stopSSE();
            loadQueue();
        } catch (e) { alert('结束失败：' + e.message); }
    });

    const msgInput = $('#q-msgInput');
    const btnSend = $('#q-btnSend');
    msgInput.addEventListener('input', () => {
        btnSend.disabled = !msgInput.value.trim() || state.sending || state.currentConvStatus !== 'trainer_active';
    });
    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault(); sendMsg();
        }
    });
    btnSend.addEventListener('click', sendMsg);

    // ponytail: 提示词列表在 mount 末尾渲染一次（数据是静态常量，不需要重渲）。
    // 输入框 disabled 状态变化时通过 syncPromptsEnabled() 同步按钮可点性。
    renderPrompts();

    async function sendMsg() {
        const content = msgInput.value.trim();
        if (!content || !state.currentConvId || state.sending) return;
        state.sending = true;
        btnSend.disabled = true;
        try {
            const saved = await api.post(`/trainer/conversations/${state.currentConvId}/messages`, { content });
            msgInput.value = '';
            if (!state.messages.find(m => m.id === saved.id)) {
                state.messages.push(saved);
                appendMsg(saved);
            }
        } catch (e) { alert('发送失败：' + e.message); }
        finally {
            state.sending = false;
            btnSend.disabled = !msgInput.value.trim() || state.currentConvStatus !== 'trainer_active';
        }
    }

    // ============ 推荐模板 / 定制计划 ============
    $('#q-btnReco').addEventListener('click', () => openTemplateModal('recommend'));
    $('#q-btnCustom').addEventListener('click', () => openTemplateModal('customize'));
    $('#q-btnTemplates').addEventListener('click', () => {
        window.location.href = '/admin/templates.html';
    });
    $('#q-tplModalClose').addEventListener('click', closeTemplateModal);
    $('#q-tplModal .qp-modal__backdrop')?.addEventListener('click', closeTemplateModal);

    async function openTemplateModal(mode) {
        const modal = $('#q-tplModal');
        const title = $('#q-tplModalTitle');
        const body = $('#q-tplModalBody');
        title.textContent = mode === 'recommend' ? '📋 推荐模板给会员' : '⚡ 为会员定制计划';
        body.innerHTML = '<div class="qp-empty">加载中...</div>';
        modal.style.display = 'flex';

        try {
            // 拿所有 published 模板（C 端接口对所有人开放）
            const data = await api.get('/plan-templates?page_size=50');
            state.templatesCache = data.items || [];
            if (!state.templatesCache.length) {
                body.innerHTML = '<div class="qp-empty">暂无已发布模板</div>';
                return;
            }
            body.innerHTML = state.templatesCache.map(t => `
                <div class="qp-tpl-item" data-tid="${t.id}" style="display:flex;gap:12px;padding:12px;border-bottom:1px solid var(--color-border);cursor:pointer;align-items:center;">
                    ${t.cover_url ? `<img src="${esc(t.cover_url)}" style="width:60px;height:60px;object-fit:cover;border-radius:6px;">` : '<div style="width:60px;height:60px;background:#e5e7eb;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#9ca3af;">📋</div>'}
                    <div style="flex:1;">
                        <div style="font-weight:500;">${esc(t.name)}</div>
                        <div style="font-size:12px;color:#6b7280;">${esc(t.goal)} · ${esc(t.level)} · 采用 ${t.use_count} 次</div>
                    </div>
                    ${mode === 'recommend' ? '<button class="qp-btn-rec" data-tid="' + t.id + '" style="padding:4px 12px;background:#10b981;color:white;border:none;border-radius:4px;cursor:pointer;">推荐</button>' : '<button class="qp-btn-cus" data-tid="' + t.id + '" style="padding:4px 12px;background:#3b82f6;color:white;border:none;border-radius:4px;cursor:pointer;">定制</button>'}
                </div>
            `).join('');

            if (mode === 'recommend') {
                body.querySelectorAll('.qp-btn-rec').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        try {
                            const saved = await api.post(`/trainer/conversations/${state.currentConvId}/recommend-template`, { template_id: +btn.dataset.tid });
                            state.messages.push(saved);
                            appendMsg(saved);
                            closeTemplateModal();
                        } catch (e) { alert('推荐失败：' + e.message); }
                    });
                });
            } else {
                body.querySelectorAll('.qp-btn-cus').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const t = state.templatesCache.find(x => x.id === +btn.dataset.tid);
                        const name = prompt('计划名（留空用模板名）', t?.name || '');
                        if (name === null) return;
                        try {
                            const res = await api.post(`/trainer/conversations/${state.currentConvId}/customize-plan`, { template_id: +btn.dataset.tid, name: name || null });
                            // 拉最新消息（customize-plan 写入了一条系统消息）
                            state.messages = await api.get(`/trainer/conversations/${state.currentConvId}/messages`);
                            renderMessages();
                            closeTemplateModal();
                            alert(`已为会员定制计划 #${res.plan_id}`);
                        } catch (e) { alert('定制失败：' + e.message); }
                    });
                });
            }
        } catch (e) {
            body.innerHTML = `<div class="qp-empty">加载失败：${esc(e.message)}</div>`;
        }
    }

    function closeTemplateModal() {
        $('#q-tplModal').style.display = 'none';
    }

    // ============ SSE ============
    function stopSSE() {
        if (state.sseAbort) { state.sseAbort.abort(); state.sseAbort = null; }
    }

    function startSSE() {
        stopSSE();
        if (!state.currentConvId) return;
        const token = localStorage.getItem(TOKEN_KEY);
        const ctrl = new AbortController();
        state.sseAbort = ctrl;

        fetch(`/api/v1/trainer/conversations/${state.currentConvId}/stream`, {
            method: 'GET',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            signal: ctrl.signal,
        }).then(async (resp) => {
            if (!resp.ok || !resp.body) return;
            const reader = resp.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buf = '';
            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buf += decoder.decode(value, { stream: true })
                        .replace(/\r\n/g, '\n').replace(/\r/g, '\n');
                    let sep;
                    while ((sep = buf.indexOf('\n\n')) !== -1) {
                        const raw = buf.slice(0, sep);
                        buf = buf.slice(sep + 2);
                        for (const line of raw.split('\n')) {
                            const t = line.trim();
                            if (!t.startsWith('data:')) continue;
                            const payload = t.slice(5).trim();
                            if (!payload) continue;
                            try {
                                const ev = JSON.parse(payload);
                                if (ev.type === 'message') {
                                    const m = ev.message;
                                    if (!state.messages.find(x => x.id === m.id)) {
                                        state.messages.push(m);
                                        appendMsg(m);
                                    }
                                } else if (ev.type === 'status') {
                                    applyStatus(ev.status);
                                }
                            } catch (e) { /* ignore parse error */ }
                        }
                    }
                }
            } catch (e) {
                if (e && e.name !== 'AbortError') console.error('[trainer] SSE reader:', e);
            }
        }).catch((e) => {
            if (e && e.name !== 'AbortError') console.warn('SSE error:', e);
        });
    }
}

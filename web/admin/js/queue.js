/**
 * 会话工作台模块（嵌入 dashboard.html）。
 *
 * 用法：
 *   <section id="queuePanel"></section>
 *   <script type="module">
 *     import { mountQueue } from './js/queue.js';
 *     mountQueue('queuePanel');
 *   </script>
 *
 * 原本曾在独立的 queue.html 页面，已合并到数据看板；ID 全部加 `q-` 前缀避免与宿主页面冲突。
 */

const TOKEN_KEY = 'fithub_admin_access';
const REFRESH_KEY = 'fithub_admin_refresh';
const USER_KEY = 'fithub_admin_user';

const HTML = `
<div class="qp-card">
  <div class="qp-toolbar">
    <div class="qp-tabs">
      <button class="qp-tab qp-tab--active" data-tab="queue">📥 待接入队列</button>
      <button class="qp-tab" data-tab="history">📜 我的会话</button>
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
      <div class="qp-user-pane__head">👤 用户信息</div>
      <div id="q-userCard" class="qp-user-card">
        <div class="qp-user-card__empty">选择会话后展示</div>
      </div>
    </aside>
  </div>
</div>
`;

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

export function mountQueue(rootId) {
    const root = document.getElementById(rootId);
    if (!root) return;
    root.innerHTML = HTML;

    const user = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    if (!localStorage.getItem(TOKEN_KEY) || !user) {
        root.innerHTML = '<div class="qp-empty">未登录</div>';
        return;
    }
    if (!['customer_service', 'trainer', 'admin'].includes(user.role)) {
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
        delete: (p) => api.request(p, { method: 'DELETE' }),
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
        historyLoaded: false,
    };

    // ============ Tab 切换 ============
    document.querySelectorAll('.qp-tab').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    function switchTab(tab) {
        if (state.tab === tab) return;
        state.tab = tab;
        document.querySelectorAll('.qp-tab').forEach(b => {
            b.classList.toggle('qp-tab--active', b.dataset.tab === tab);
        });
        if (tab === 'queue') {
            renderQueue();
        } else {
            loadHistory();
        }
    }

    // ============ 队列 ============
    async function loadQueue() {
        try {
            state.queue = await api.get('/admin/cs/queue');
            renderQueue();
        } catch (e) {
            console.error('队列加载失败:', e);
        }
    }

    function renderQueue() {
        const wrap = document.getElementById('q-queueList');
        if (!wrap) return;
        if (!state.queue.length) {
            wrap.innerHTML = '<div class="qp-empty">📭 暂无待接入</div>';
            return;
        }
        wrap.innerHTML = state.queue.map(c => {
            const waitMin = Math.floor((Date.now() - new Date(c.waiting_since).getTime()) / 60000);
            const wait = waitMin < 1 ? '刚刚' : `${waitMin} 分钟`;
            return `
                <div class="qp-queue-item ${c.conversation_id === state.currentConvId ? 'qp-queue-item--active' : ''}" data-cid="${c.conversation_id}">
                    <div class="qp-queue-item__title">${esc(c.nickname || c.username)} <span style="font-weight:400;color:#6b7280;font-size:12px;">· ${esc(c.title)}</span></div>
                    <div class="qp-queue-item__meta">等待 ${wait} · 会话 #${c.conversation_id}</div>
                    <div class="qp-queue-item__preview">${esc(c.last_message || '—')}</div>
                </div>
            `;
        }).join('');
        wrap.querySelectorAll('.qp-queue-item').forEach(el => {
            el.addEventListener('click', () => selectConversation(+el.dataset.cid));
        });
    }

    document.getElementById('q-btnRefresh').addEventListener('click', loadQueue);
    setInterval(() => { if (state.tab === 'queue') loadQueue(); }, 5000);
    loadQueue();

    // ============ 历史会话 ============
    async function loadHistory() {
        try {
            state.history = await api.get('/admin/cs/conversations/history');
            state.historyLoaded = true;
            renderHistory();
        } catch (e) {
            console.error('加载历史会话失败:', e);
            const wrap = document.getElementById('q-queueList');
            if (wrap) wrap.innerHTML = '<div class="qp-empty">加载失败</div>';
        }
    }

    function renderHistory() {
        const wrap = document.getElementById('q-queueList');
        if (!wrap) return;
        if (!state.history.length) {
            wrap.innerHTML = '<div class="qp-empty">📭 暂无历史会话</div>';
            return;
        }
        wrap.innerHTML = state.history.map(c => {
            const when = c.updated_at ? new Date(c.updated_at).toLocaleString('zh-CN') : '';
            const statusLabel = statusBadge(c.status);
            return `
                <div class="qp-queue-item ${c.conversation_id === state.currentConvId ? 'qp-queue-item--active' : ''}" data-cid="${c.conversation_id}" data-from="history">
                    <div class="qp-queue-item__title">
                        ${esc(c.nickname || c.username)}
                        <span style="font-weight:400;color:#6b7280;font-size:12px;">· ${esc(c.title)}</span>
                        ${statusLabel}
                        <button class="qp-item-del" data-del-cid="${c.conversation_id}" title="删除会话">🗑</button>
                    </div>
                    <div class="qp-queue-item__meta">#${c.conversation_id} · ${esc(when)}</div>
                    <div class="qp-queue-item__preview">${esc(c.last_message || '—')}</div>
                </div>
            `;
        }).join('');
        wrap.querySelectorAll('[data-from="history"]').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.closest('[data-del-cid]')) return;  // 点删除按钮不触发选中
                selectHistoryConversation(+el.dataset.cid);
            });
        });
        wrap.querySelectorAll('[data-del-cid]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                await deleteHistoryConv(+btn.dataset.delCid);
            });
        });
    }

    async function deleteHistoryConv(convId) {
        const item = state.history.find(c => c.conversation_id === convId);
        const label = item ? `${item.nickname || item.username} #${convId}` : `#${convId}`;
        if (!confirm(`确定删除会话 ${label}？\n该会话所有消息将一并删除，无法恢复。`)) return;
        try {
            await api.delete(`/admin/cs/conversations/${convId}`);
            // 若当前正查看的就是这个，清空右侧
            if (state.currentConvId === convId) {
                state.currentConvId = null;
                state.currentConv = null;
                state.messages = [];
                document.getElementById('q-chatTitle').textContent = '请选择会话';
                document.getElementById('q-chatSub').textContent = '左侧选一个会话开始';
                document.getElementById('q-chatMessages').innerHTML = '<div class="qp-empty">左侧选一个会话开始</div>';
                document.getElementById('q-chatStatusBar').style.display = 'none';
                renderUserCard();
            }
            // 从本地数组移除并重渲（不动 queue tab，避免影响其他视图）
            state.history = state.history.filter(c => c.conversation_id !== convId);
            renderHistory();
        } catch (e) {
            alert('删除失败：' + e.message);
        }
    }

    function statusBadge(status) {
        const m = {
            ai_active: '<span style="font-size:11px;color:#9ca3af;background:rgba(156,163,175,0.15);padding:1px 6px;border-radius:4px;margin-left:4px;">AI</span>',
            waiting_human: '<span style="font-size:11px;color:#fbbf24;background:rgba(251,191,36,0.15);padding:1px 6px;border-radius:4px;margin-left:4px;">等待</span>',
            human_active: '<span style="font-size:11px;color:#22c55e;background:rgba(34,197,94,0.15);padding:1px 6px;border-radius:4px;margin-left:4px;">服务中</span>',
            closed: '<span style="font-size:11px;color:#ef4444;background:rgba(239,68,68,0.15);padding:1px 6px;border-radius:4px;margin-left:4px;">已结束</span>',
        };
        return m[status] || '';
    }

    async function selectHistoryConversation(convId) {
        if (state.currentConvId !== convId) stopSSE();
        state.currentConvId = convId;
        const h = state.history.find(c => c.conversation_id === convId);
        if (h) {
            state.currentConv = {
                id: h.conversation_id, user_id: h.user_id,
                username: h.username, nickname: h.nickname, title: h.title,
                status: h.status,
            };
        }
        renderHistory();
        const displayName = state.currentConv?.nickname || state.currentConv?.username || '会话';
        document.getElementById('q-chatTitle').textContent = `${displayName} #${convId}`;
        document.getElementById('q-chatSub').textContent = '📜 历史会话（只读）';
        renderUserCard();
        try {
            state.messages = await api.get(`/admin/cs/conversations/${convId}/messages`);
            renderMessages();
        } catch (e) {
            console.error('消息加载失败:', e);
        }
        // 历史只读：不启 SSE，不允许 claim/close/send
        applyStatus(h?.status || 'ai_active', { readonly: true });
    }

    // ============ 选中会话 ============
    async function selectConversation(convId) {
        if (state.currentConvId !== convId) stopSSE();
        state.currentConvId = convId;
        const qi = state.queue.find(c => c.conversation_id === convId);
        if (qi) {
            state.currentConv = {
                id: qi.conversation_id, user_id: qi.user_id,
                username: qi.username, nickname: qi.nickname, title: qi.title,
                status: qi.status,  // 用队列返回的真实 status
            };
        }
        renderQueue();
        const displayName = state.currentConv?.nickname || state.currentConv?.username || `会话 #${convId}`;
        document.getElementById('q-chatTitle').textContent = displayName;
        document.getElementById('q-chatSub').textContent = state.currentConv?.title || '—';
        renderUserCard();
        try {
            state.messages = await api.get(`/admin/cs/conversations/${convId}/messages`);
            renderMessages();
        } catch (e) {
            console.error('消息加载失败:', e);
        }
        // 关键修复：用队列返回的真实 status 初始化，避免 race condition
        // 之前这里硬编码 'human_active'，导致 waiting_human 时也能点发送 → 400
        applyInitialStatus(qi?.status || 'waiting_human');
        startSSE();
    }

    // 初次进入会话：根据当前状态设置 UI，但不做"刷新"动作
    function applyInitialStatus(status) {
        applyStatus(status || 'waiting_human');
    }

    function applyStatus(status, opts = {}) {
        state.currentConvStatus = status;
        const bar = document.getElementById('q-chatStatusBar');
        const btnClaim = document.getElementById('q-btnClaim');
        const btnClose = document.getElementById('q-btnClose');
        const msgInput = document.getElementById('q-msgInput');
        const btnSend = document.getElementById('q-btnSend');

        if (opts.readonly) {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--closed';
            bar.textContent = opts.label || '📜 历史会话（只读）';
            btnClaim.disabled = true; btnClose.disabled = true;
            msgInput.disabled = true; btnSend.disabled = true;
            msgInput.placeholder = opts.inputPlaceholder || '只读模式，不可发送';
            return;
        }

        if (status === 'waiting_human') {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--waiting';
            bar.textContent = '🟡 等待接入';
            btnClaim.disabled = false; btnClose.disabled = true;
            msgInput.disabled = true; btnSend.disabled = true;
        } else if (status === 'ai_active') {
            // CS 关闭后回到 ai_active（conv 已不属于本 CS 了）
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--closed';
            bar.textContent = '✅ 已结束本次服务，会话已转回 AI 教练';
            btnClaim.disabled = true; btnClose.disabled = true;
            msgInput.disabled = true; btnSend.disabled = true;
            msgInput.placeholder = '已结束，等待用户与 AI 继续对话';
        } else {
            bar.style.display = 'block';
            bar.className = 'qp-chat__status qp-chat__status--human';
            bar.textContent = '🟢 你已接入此会话';
            btnClaim.disabled = true; btnClose.disabled = false;
            msgInput.disabled = false; btnSend.disabled = false;
        }
    }

    function renderMessages() {
        const wrap = document.getElementById('q-chatMessages');
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
        const avatar = m.sender_type === 'customer_service' ? '我' : (m.sender_type === 'ai' ? 'AI' : '用户');
        return `
            <div class="qp-msg qp-msg--${m.sender_type}">
                <div class="qp-msg__avatar">${avatar}</div>
                <div>
                    <div class="qp-msg__bubble">${esc(m.content)}</div>
                    <div class="qp-msg__time">${time}</div>
                </div>
            </div>
        `;
    }

    function appendMsg(m) {
        const wrap = document.getElementById('q-chatMessages');
        const empty = wrap.querySelector('.qp-empty');
        if (empty) empty.remove();
        const tmp = document.createElement('div');
        tmp.innerHTML = renderMsgHTML(m);
        wrap.appendChild(tmp.firstElementChild);
        wrap.scrollTop = wrap.scrollHeight;
    }

    function renderUserCard() {
        const wrap = document.getElementById('q-userCard');
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

    // ============ 接入 / 结束 / 发送 ============
    document.getElementById('q-btnClaim').addEventListener('click', async () => {
        if (!state.currentConvId) return;
        try {
            await api.post(`/admin/cs/conversations/${state.currentConvId}/claim`);
            applyStatus('human_active');
            startSSE();
        } catch (e) { alert('接入失败：' + e.message); }
    });

    document.getElementById('q-btnClose').addEventListener('click', async () => {
        if (!state.currentConvId) return;
        if (!confirm('确定结束该会话？结束后用户可继续与 AI 对话。')) return;
        try {
            await api.post(`/admin/cs/conversations/${state.currentConvId}/close`);
            // 后端现在会把 status 改回 ai_active + 插入 CS 结束消息，SSE 会推过来
            // 这里立刻禁用交互，等 SSE 把 ai_active 事件推过来后再正式显示"已结束"标签
            applyStatus('ai_active');  // 触发"已结束本次服务"UI
            stopSSE();
        } catch (e) { alert('结束失败：' + e.message); }
    });

    const msgInput = document.getElementById('q-msgInput');
    const btnSend = document.getElementById('q-btnSend');
    msgInput.addEventListener('input', () => {
        btnSend.disabled = !msgInput.value.trim() || state.sending || state.currentConvStatus !== 'human_active';
    });
    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault(); sendMsg();
        }
    });
    btnSend.addEventListener('click', sendMsg);

    async function sendMsg() {
        const content = msgInput.value.trim();
        if (!content || !state.currentConvId || state.sending) return;
        state.sending = true;
        btnSend.disabled = true;
        try {
            const saved = await api.post(`/admin/cs/conversations/${state.currentConvId}/messages`, { content });
            msgInput.value = '';
            if (!state.messages.find(m => m.id === saved.id)) {
                state.messages.push(saved);
                appendMsg(saved);
            }
        } catch (e) { alert('发送失败：' + e.message); }
        finally {
            state.sending = false;
            btnSend.disabled = !msgInput.value.trim() || state.currentConvStatus !== 'human_active';
        }
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

        fetch(`/api/v1/admin/cs/conversations/${state.currentConvId}/stream`, {
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
                    // 后端 SSE 用 CRLF 行尾，归一为 LF 否则 buf.indexOf('\n\n') 匹配不到
                    buf += decoder.decode(value, { stream: true })
                        .replace(/\r\n/g, '\n')
                        .replace(/\r/g, '\n');
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
                            } catch (e) {
                                console.warn('SSE parse:', e, payload);
                            }
                        }
                    }
                }
            } catch (e) {
                // AbortError 是 stopSSE() 主动触发，内层静默吃掉，避免 dev tools 暂停
                if (e && e.name !== 'AbortError') console.error('[admin] SSE reader:', e);
            }
        }).catch((e) => {
            if (e && e.name !== 'AbortError') console.warn('SSE error:', e);
        });
    }
}
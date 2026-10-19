/**
 * AI 教练 Tab 模块（M5: 转人工 + SSE 双向）
 *
 * 依赖：api（来自 ./api.js）
 * 用法：
 *   import { mountChat } from './chat-tab.js';
 *   mountChat({ escapeHtml });
 */
import { api, tokenStore } from './api.js';

const chatState = {
    conversations: [],
    currentConvId: null,
    currentConvStatus: 'ai_active',  // ai_active / waiting_human / human_active / closed
    messages: [],
    sending: false,
    streamAbort: null,
    sseAbort: null,  // 当前会话的 SSE 监听 AbortController
    sseWantRun: false,  // 是否希望保持 SSE 连接
    pollTimer: null,  // 轮询定时器（SSE 失败时的兜底）
    sseConnected: false,  // 当前 SSE 是否真正连上
};

// 模块级 escape 函数，mountChat 时赋值。供 loadConversations 等异步函数使用
let esc = (s) => String(s ?? '');

async function loadConversations() {
    try {
        const convs = await api.get('/conversations');
        chatState.conversations = convs;
        renderConvList();
    } catch (e) {
        console.error('加载会话列表失败：', e);
        // 401 已被 api.js 跳转到登录页；其它错误给个轻提示
        if (e.status && e.status !== 401) {
            document.getElementById('chatTitle').textContent = '加载失败';
        }
    }
}

function renderConvList() {
    const wrap = document.getElementById('convList');
    if (chatState.conversations.length === 0) {
        wrap.innerHTML = '<p style="color: var(--text-muted); font-size: var(--font-size-xs); text-align: center; padding: var(--space-3);">还没有会话</p>';
        return;
    }
    wrap.innerHTML = chatState.conversations.map(c => `
        <div class="chat-conv-item ${c.id === chatState.currentConvId ? 'chat-conv-item--active' : ''}" data-conv-id="${c.id}">
            <div class="chat-conv-item__row">
                <div class="chat-conv-item__title">${esc(c.title)}</div>
                <button class="chat-conv-item__del" data-del-id="${c.id}" title="删除会话">🗑</button>
            </div>
            <div class="chat-conv-item__preview">${esc(c.last_message || '—')}</div>
        </div>
    `).join('');
    wrap.querySelectorAll('.chat-conv-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('[data-del-id]')) return;
            loadConversation(+item.dataset.convId);
        });
    });
    wrap.querySelectorAll('[data-del-id]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = +btn.dataset.delId;
            const conv = chatState.conversations.find(c => c.id === id);
            if (!confirm(`确定删除会话「${conv?.title || '该会话'}」？`)) return;
            try {
                await api.delete(`/conversations/${id}`);
                chatState.conversations = chatState.conversations.filter(c => c.id !== id);
                if (chatState.currentConvId === id) {
                    chatState.currentConvId = null;
                    chatState.currentConvStatus = 'ai_active';
                    chatState.messages = [];
                    document.getElementById('chatTitle').textContent = 'AI 教练 FitCoach';
                    renderMessages();
                    updateStatusBanner();
                    stopSSE();
                }
                renderConvList();
            } catch (err) {
                alert('删除失败：' + err.message);
            }
        });
    });
}

async function loadConversation(convId) {
    chatState.currentConvId = convId;
    renderConvList();
    const conv = chatState.conversations.find(c => c.id === convId);
    if (conv) document.getElementById('chatTitle').textContent = conv.title;
    try {
        const msgs = await api.get(`/conversations/${convId}/messages`);
        chatState.messages = msgs;
        renderMessages();
    } catch (e) {
        if (e.status !== 401) alert('加载消息失败：' + e.message);
    }

    // 拉会话状态，决定 banner + 是否启 SSE
    try {
        const status = await api.get(`/conversations/${convId}/status`);
        applyConvStatus(status.status);
    } catch (e) {
        if (e.status !== 401) applyConvStatus('ai_active');
    }
}

function renderMessages() {
    const wrap = document.getElementById('messages');
    if (chatState.messages.length === 0) {
        wrap.innerHTML = `
            <div class="chat-empty">
                <div class="chat-empty__art">💬</div>
                <div class="chat-empty__title">会话已创建</div>
                <div class="chat-empty__desc">开始输入消息吧！</div>
            </div>
        `;
        return;
    }
    wrap.innerHTML = chatState.messages.map(m => {
        const r = renderMsg(m);
        return r.msgHtml + renderTemplateSuggestions(r.suggestions);
    }).join('');
    bindAdoptButtons();
    scrollToBottom();
}

function bindAdoptButtons() {
    const wrap = document.getElementById('messages');
    wrap.querySelectorAll('[data-adopt-tid]').forEach(btn => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', () => adoptTemplate(+btn.dataset.adoptTid, btn));
    });
    wrap.querySelectorAll('[data-adopt]').forEach(btn => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', () => adoptTemplate(+btn.dataset.adopt, btn));
    });
}

function renderMsg(m) {
    const time = new Date(m.created_at || Date.now()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const isUser = m.sender_type === 'user';
    const avatarText = isUser ? '我'
        : (m.sender_type === 'trainer' ? '教练'
        : (m.sender_type === 'system' ? '·' : 'AI'));

    // 教练推荐的模板卡片（M8）
    if (m.sender_type === 'trainer' && m.extra?.kind === 'recommend_template') {
        const t = m.extra.template || {};
        return `
            <div class="msg msg--trainer" data-mid="${m.id ?? ''}" data-tpl-id="${t.id ?? ''}">
                <div class="msg__avatar">教练</div>
                <div>
                    <div class="msg__bubble">
                        <div class="trainer-card__title">📋 教练为你推荐了训练模板</div>
                        ${t.cover_url ? `<img class="trainer-card__cover" src="${esc(t.cover_url)}" alt="">` : ''}
                        <div class="trainer-card__name">${esc(t.name || '—')}</div>
                        <div class="trainer-card__meta">${esc(t.goal || '')} · ${esc(t.level || '')}</div>
                        ${t.description ? `<div class="trainer-card__desc">${esc(t.description)}</div>` : ''}
                        <div class="trainer-card__actions">
                            <button class="trainer-card__btn trainer-card__btn--adopt" data-adopt-tid="${t.id}">✅ 采用为我的计划</button>
                            ${t.id ? `<a class="trainer-card__btn trainer-card__btn--view" href="/c/template-detail.html?id=${t.id}" target="_blank">查看详情</a>` : ''}
                        </div>
                    </div>
                    <div class="msg__time">${time}</div>
                </div>
            </div>
        `;
    }
    // 教练定制计划卡片（M8）
    if (m.sender_type === 'trainer' && m.extra?.kind === 'customize_plan') {
        return `
            <div class="msg msg--trainer" data-mid="${m.id ?? ''}">
                <div class="msg__avatar">教练</div>
                <div>
                    <div class="msg__bubble">
                        <div class="trainer-card__title">⚡ 教练为你定制了训练计划</div>
                        <div class="trainer-card__desc">${esc(m.content || '已为你定制计划，请查收')}</div>
                        <a class="trainer-card__plan-link" href="/c/plans.html?focus=${m.extra?.plan_id}">📄 查看计划 #${m.extra?.plan_id}</a>
                    </div>
                    <div class="msg__time">${time}</div>
                </div>
            </div>
        `;
    }

    // 状态化气泡：loading（思考中三点）/ streaming（流式光标）/ error（红色错误）
    let bubbleInner, bubbleExtraClass = '';
    if (m._status === 'loading') {
        bubbleInner = '<span class="chat-typing"><span></span><span></span><span></span></span>';
        bubbleExtraClass = ' msg__bubble--loading';
    } else if (m._status === 'streaming') {
        bubbleInner = esc(m.content || '');
        bubbleExtraClass = ' msg__bubble--streaming';
    } else if (m._status === 'error') {
        bubbleInner = esc(m.content || '');
        bubbleExtraClass = ' msg__bubble--error';
    } else {
        bubbleInner = esc(m.content || '');
    }

    return {
        msgHtml: `
        <div class="msg msg--${m.sender_type}" data-mid="${m.id ?? ''}">
            <div class="msg__avatar">${avatarText}</div>
            <div>
                <div class="msg__bubble${bubbleExtraClass}">${bubbleInner}</div>
                <div class="msg__time">${time}</div>
            </div>
        </div>`,
        suggestions: Array.isArray(m.extra?.template_suggestions) ? m.extra.template_suggestions : [],
    };
}

const GOAL_LABEL = { muscle_gain: '增肌', fat_loss: '减脂', body_shape: '塑形', endurance: '体能' };
const LEVEL_LABEL = { beginner: '新手', intermediate: '有基础', advanced: '老手' };

function renderTemplateSuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) return '';
    return `
        <div class="tpl-suggest">
            <div class="tpl-suggest__title">📋 教练为你挑了几套现成计划，挑一个试试：</div>
            <div class="tpl-suggest__list">
                ${suggestions.map(s => `
                    <div class="tpl-card" data-tpl-id="${s.id}">
                        <div class="tpl-card__head">
                            <div class="tpl-card__name">${esc(s.name || '未命名模板')}</div>
                            <div class="tpl-card__tags">
                                <span class="tpl-tag">${GOAL_LABEL[s.goal] || s.goal}</span>
                                <span class="tpl-tag tpl-tag--mute">${LEVEL_LABEL[s.level] || s.level}</span>
                                ${s.weeks_count > 0 ? `<span class="tpl-tag tpl-tag--mute">${s.weeks_count} 周</span>` : ''}
                            </div>
                        </div>
                        ${s.description ? `<div class="tpl-card__desc">${esc(s.description)}</div>` : ''}
                        <div class="tpl-card__foot">
                            <span class="tpl-card__meta">已 ${s.use_count || 0} 人采用${s.avg_rating > 0 ? ` · ★ ${s.avg_rating.toFixed(1)}` : ''}</span>
                            <button class="tpl-card__btn" data-adopt="${s.id}">✅ 采用到我的计划</button>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function appendMessageDOM(m) {
    const wrap = document.getElementById('messages');
    const empty = wrap.querySelector('.chat-empty');
    if (empty) empty.remove();
    const tmp = document.createElement('div');
    const rendered = renderMsg(m);
    tmp.innerHTML = rendered.msgHtml + renderTemplateSuggestions(rendered.suggestions);
    // append all child nodes (msg div + optional tpl-suggest block)
    while (tmp.firstChild) wrap.appendChild(tmp.firstChild);
    bindAdoptButtons();
    wrap.scrollTop = wrap.scrollHeight;
    return wrap.lastElementChild;
}

// ============ 状态 & 横幅 ============

function applyConvStatus(status) {
    chatState.currentConvStatus = status;
    updateStatusBanner();
    // waiting_human / human_active / waiting_trainer / trainer_active 都启 SSE，其它都停
    if (chatState.currentConvId) {
        if (['waiting_human', 'human_active', 'waiting_trainer', 'trainer_active'].includes(status)) {
            startSSE();
            startPolling();  // 兜底：SSE 漏接时也能拉新消息
        } else {
            stopSSE();
            stopPolling();
        }
    }
    // 切换按钮可用性
    const btn = document.getElementById('btnTransfer');
    const btnTrainer = document.getElementById('btnFindTrainer');
    const input = document.getElementById('msgInput');
    const btnSend = document.getElementById('btnSend');
    // ponytail: 教练兼客服（合并），转人工 = 转教练；禁用互斥按钮避免重复触发
    if (btn) btn.disabled = ['waiting_human', 'human_active', 'waiting_trainer', 'trainer_active'].includes(status);
    if (btnTrainer) btnTrainer.disabled = ['waiting_human', 'human_active', 'waiting_trainer', 'trainer_active'].includes(status);
    // 输入框策略：
    //   - ai_active：用户继续和 AI 对话
    //   - waiting_human / waiting_trainer：通知接入中，仍可与 AI 对话
    //   - human_active / trainer_active：与教练/原 CS 接入者对话
    if (input && btnSend) {
        input.disabled = false;
        if (status === 'waiting_human' || status === 'waiting_trainer') {
            input.placeholder = '已通知教练接入中，仍可继续与 AI 对话...';
        } else if (status === 'human_active' || status === 'trainer_active') {
            input.placeholder = '教练正在为你服务...';
        } else {
            input.placeholder = '输入消息，Enter 发送，Shift+Enter 换行...';
        }
        btnSend.disabled = !input.value.trim() || chatState.sending;
    }
}

function updateStatusBanner() {
    const banner = document.getElementById('chatStatus');
    const s = chatState.currentConvStatus;
    if (!banner) return;
    const connLabel = chatState.sseConnected
        ? '<span style="color:#4ade80;font-size:11px;margin-left:8px;">● 实时</span>'
        : (['waiting_human', 'human_active', 'waiting_trainer', 'trainer_active'].includes(s))
            ? '<span style="color:#fbbf24;font-size:11px;margin-left:8px;">● 轮询中</span>'
            : '';
    if (s === 'waiting_human' || s === 'waiting_trainer') {
        banner.hidden = false;
        banner.className = 'chat-status';
        banner.innerHTML = `🏋️ 已通知教练接入中，等待期间仍可继续与 AI 对话${connLabel}`;
    } else if (s === 'human_active' || s === 'trainer_active') {
        banner.hidden = false;
        banner.className = 'chat-status chat-status--active';
        banner.innerHTML = `✅ 教练已接入，正在为你服务${connLabel}`;
    } else {
        banner.hidden = true;  // ai_active / 其它都不再显示 banner
    }
}

// ============ SSE ============

function stopSSE() {
    if (chatState.sseAbort) {
        chatState.sseAbort.abort();
        chatState.sseAbort = null;
    }
    // 关掉自动重连标记，避免 stopSSE 后又自动起
    chatState.sseWantRun = false;
    chatState.sseConnected = false;
    updateStatusBanner();
}

async function startSSE() {
    stopSSE();
    if (!chatState.currentConvId) return;
    chatState.sseWantRun = true;  // 标记希望持续监听，错误时自动重连
    const ctrl = new AbortController();
    chatState.sseAbort = ctrl;

    const convId = chatState.currentConvId;
    const url = `/api/v1/conversations/${convId}/stream`;
    console.log(`[chat] SSE connecting → ${url}`);

    try {
        const resp = await fetch(url, {
            method: 'GET',
            headers: tokenStore.access ? { 'Authorization': `Bearer ${tokenStore.access}` } : {},
            signal: ctrl.signal,
        });
        if (!resp.ok || !resp.body) {
            console.warn(`[chat] SSE failed: HTTP ${resp.status}`);
            scheduleReconnect();
            return;
        }
        console.log('[chat] SSE connected');
        chatState.sseConnected = true;
        updateStatusBanner();

        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buf = '';
        // eslint-disable-next-line no-constant-condition
        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    console.log('[chat] SSE closed by server');
                    scheduleReconnect();
                    return;
                }
                // SSE 规范允许 CRLF / CR / LF 行尾，后端发的是 CRLF；
                // 归一为 LF，否则 buf.indexOf('\n\n') 匹配不到 \r\n\r\n
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
                            handleSSEEvent(JSON.parse(payload));
                        } catch (e) {
                            console.warn('SSE parse:', e, payload);
                        }
                    }
                }
            }
        } catch (e) {
            // AbortError 是 stopSSE() 主动触发，内层静默吃掉
            if (e && e.name !== 'AbortError') {
                console.warn('[chat] SSE reader:', e);
                scheduleReconnect();
            }
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log('[chat] SSE aborted (manual stop or conv change)');
            return;  // 主动 abort 不重连
        }
        console.warn('[chat] SSE conn error:', e);
        scheduleReconnect();
    }
}

// 自动重连（仅当用户期望监听时）
function scheduleReconnect() {
    if (!chatState.sseWantRun) return;
    if (!chatState.currentConvId) return;
    // 当前会话状态不是人工态就不必重连
    const s = chatState.currentConvStatus;
    if (s !== 'waiting_human' && s !== 'human_active') return;
    console.log('[chat] SSE reconnect in 3s...');
    chatState.sseConnected = false;
    updateStatusBanner();
    setTimeout(() => {
        if (chatState.sseWantRun && chatState.currentConvId) startSSE();
    }, 3000);
}

// ============ 轮询兜底 ============

function startPolling() {
    stopPolling();
    chatState.pollTimer = setInterval(async () => {
        if (!chatState.currentConvId) return;
        try {
            const msgs = await api.get(`/conversations/${chatState.currentConvId}/messages`);
            mergeMessages(msgs);
        } catch (e) {
            // 401 已处理；其它忽略
        }
    }, 5000);
}

function stopPolling() {
    if (chatState.pollTimer) {
        clearInterval(chatState.pollTimer);
        chatState.pollTimer = null;
    }
}

// 把后端最新消息列表合并进 chatState.messages（按 id 去重 + 替换乐观插入）
function mergeMessages(serverMsgs) {
    if (!Array.isArray(serverMsgs)) return;
    const existingIds = new Set(chatState.messages.map(m => m.id).filter(Boolean));
    let replaced = 0;
    let added = 0;

    // 先尝试把乐观插入（id=null 且 sender_type=user）的换成真消息
    for (const m of serverMsgs) {
        if (m.sender_type === 'user' && m.id) {
            const idx = chatState.messages.findIndex(
                x => x.sender_type === 'user' && x.content === m.content && !x.id
            );
            if (idx >= 0) {
                chatState.messages[idx] = m;
                existingIds.add(m.id);
                replaced++;
                continue;  // 不再走下面"按 id 加"分支
            }
        }
        if (m.id && !existingIds.has(m.id)) {
            chatState.messages.push(m);
            existingIds.add(m.id);
            added++;
        }
    }
    if (added > 0 || replaced > 0) {
        renderMessages();
    }
}

function handleSSEEvent(ev) {
    console.log(`[chat] SSE event: ${ev.type}`, ev);
    if (ev.type === 'message') {
        const m = ev.message;
        console.log(`[chat] 新消息 id=${m.id} sender=${m.sender_type} content=${m.content?.slice(0, 30)}...`);
        const wrap = document.getElementById('messages');

        // 用户消息：本地通常已有乐观插入（id=null），把同内容+无 id 的占位换成真消息（拿到 id），避免重复
        if (m.sender_type === 'user' && m.id) {
            const optimisticIdx = chatState.messages.findIndex(
                x => x.sender_type === 'user' && x.content === m.content && !x.id
            );
            if (optimisticIdx >= 0) {
                chatState.messages[optimisticIdx] = m;
                const oldEl = wrap.querySelector(`.msg[data-mid=""]`);
                // 上面选择器可能匹配多个；按内容缩窄
                const allEmpty = Array.from(wrap.querySelectorAll('.msg[data-mid=""]'));
                const target = allEmpty.find(el => el.querySelector('.msg__bubble')?.textContent === m.content);
                if (target) {
                    target.dataset.mid = m.id;
                    console.log(`[chat] ↺ 替换乐观插入 id=null → id=${m.id}`);
                    return;
                }
                // 找不到对应 DOM（可能已被 renderMessages 重渲过），整体重渲
                renderMessages();
                return;
            }
        }

        // 严格按 id 去重（用户 / AI / 教练 / 系统）
        if (!chatState.messages.find(x => x.id === m.id)) {
            chatState.messages.push(m);
            const tmp = document.createElement('div');
            tmp.textContent = m.content;
            const safe = tmp.innerHTML;
            const time = new Date(m.created_at || Date.now()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
            const isUser = m.sender_type === 'user';
            // ponytail: 'customer_service' 视为教练（M12 迁移完成后将不再出现，仅兼容历史会话）
            const isTrainer = m.sender_type === 'trainer' || m.sender_type === 'customer_service';
            const avatar = isUser ? '我'
                : (isTrainer ? '教练'
                : (m.sender_type === 'system' ? '·' : 'AI'));
            const empty = wrap.querySelector('.chat-empty');
            if (empty) empty.remove();
            // 教练模板/计划卡片：复用 renderMsg 走整组 DOM
            if (m.sender_type === 'trainer' && (m.extra?.kind === 'recommend_template' || m.extra?.kind === 'customize_plan')) {
                const div = document.createElement('div');
                div.innerHTML = renderMsg(m);
                const el = div.firstElementChild;
                wrap.appendChild(el);
                wrap.scrollTop = wrap.scrollHeight;
                // 给"采用"按钮绑事件
                if (m.extra?.kind === 'recommend_template') {
                    const btn = el.querySelector('[data-adopt-tid]');
                    if (btn) btn.addEventListener('click', () => adoptTemplate(+btn.dataset.adoptTid, btn));
                }
                console.log(`[chat] ✓ 渲染教练卡片 id=${m.id} kind=${m.extra.kind} 到 #messages`);
                return;
            }
            const div = document.createElement('div');
            div.className = `msg msg--${m.sender_type}`;
            div.dataset.mid = m.id || '';
            div.innerHTML = `
                <div class="msg__avatar">${avatar}</div>
                <div>
                    <div class="msg__bubble">${safe}</div>
                    <div class="msg__time">${time}</div>
                </div>
            `;
            wrap.appendChild(div);
            wrap.scrollTop = wrap.scrollHeight;
            console.log(`[chat] ✓ 渲染 id=${m.id} 到 #messages`);
        } else {
            console.log(`[chat] ⊘ id=${m.id} 已存在，跳过`);
        }
    } else if (ev.type === 'status') {
        if (ev.status !== chatState.currentConvStatus) {
            console.log(`[chat] 状态变化: ${chatState.currentConvStatus} → ${ev.status}`);
            applyConvStatus(ev.status);
        }
    }
}

// ============ 发送 ============

async function sendMessage() {
    if (chatState.sending) return;
    const input = document.getElementById('msgInput');
    const content = input.value.trim();
    if (!content) return;

    const isHuman = chatState.currentConvStatus === 'human_active';

    chatState.sending = true;
    const btnSend = document.getElementById('btnSend');
    const btnStop = document.getElementById('btnStop');
    btnSend.disabled = true;
    btnStop.hidden = true;

    // 乐观插入用户消息
    const userMsg = { id: null, sender_type: 'user', content, created_at: new Date().toISOString() };
    chatState.messages.push(userMsg);
    appendMessageDOM(userMsg);
    input.value = '';
    input.style.height = 'auto';

    // 人工事态：直接入库，CS 侧 SSE 会推送，无需流式
    if (isHuman) {
        try {
            const saved = await api.post(`/conversations/${chatState.currentConvId}/messages`, { content });
            // 把占位换成真消息
            const idx = chatState.messages.findIndex(m => m === userMsg);
            if (idx >= 0) chatState.messages[idx] = saved;
        } catch (e) {
            alert('发送失败：' + e.message);
            chatState.messages = chatState.messages.filter(m => m !== userMsg);
            renderMessages();
        } finally {
            chatState.sending = false;
            btnSend.disabled = !input.value.trim();
        }
        return;
    }

    // AI 模式：流式
    const aiPlaceholder = {
        id: null,
        sender_type: 'ai',
        content: '',
        created_at: new Date().toISOString(),
        _status: 'loading',  // loading | streaming | done | error
    };
    chatState.messages.push(aiPlaceholder);
    renderMessages();
    scrollToBottom();

    btnStop.hidden = false;

    let finalContent = '';

    chatState.streamAbort = api.stream(
        '/chat/send/stream',
        { conversation_id: chatState.currentConvId, content },
        (ev) => {
            if (ev.type === 'meta') {
                chatState.currentConvId = ev.conversation_id;
            } else if (ev.type === 'delta') {
                const idx = chatState.messages.indexOf(aiPlaceholder);
                if (idx < 0) return;  // placeholder 已被替换/移除，安全退出
                finalContent += ev.text;
                aiPlaceholder.content = finalContent;
                aiPlaceholder._status = 'streaming';
                updateAIBubble(idx, aiPlaceholder);
                scrollToBottom();
            } else if (ev.type === 'done' || ev.type === 'error') {
                const idx = chatState.messages.indexOf(aiPlaceholder);
                const finalMsg = {
                    id: ev.message_id,
                    sender_type: 'ai',
                    content: ev.content || finalContent,
                    created_at: aiPlaceholder.created_at,
                    // SSE done 携带的模板建议（plan-intent 时由后端注入）
                    extra: (() => {
                const e = {};
                if (ev.template_suggestions) e.template_suggestions = ev.template_suggestions;
                if (ev.kb_sources) e.kb_sources = ev.kb_sources;
                return Object.keys(e).length ? e : undefined;
            })(),
                };
                if (idx >= 0) {
                    chatState.messages[idx] = finalMsg;
                    renderMessages();
                    scrollToBottom();
                    // 兜底：再 setTimeout 一拍重渲染，防竞态
                    setTimeout(() => {
                        if (chatState.messages[idx] && chatState.messages[idx].id === ev.message_id) {
                            renderMessages();
                            scrollToBottom();
                        }
                    }, 50);
                }
                finishStream();
                if (ev.type === 'done') {
                    loadConversations();
                    const conv = chatState.conversations.find(c => c.id === chatState.currentConvId);
                    if (conv) document.getElementById('chatTitle').textContent = conv.title;
                }
            }
        },
        (err) => {
            console.error('AI stream error:', err);
            const idx = chatState.messages.indexOf(aiPlaceholder);
            const errMsg = {
                id: null,
                sender_type: 'ai',
                content: `⚠️ ${err.message || '请求失败'}`,
                created_at: aiPlaceholder.created_at,
                _status: 'error',
            };
            if (idx >= 0) {
                chatState.messages[idx] = errMsg;
                renderMessages();
                scrollToBottom();
            }
            finishStream();
        },
    );
}

// 按 index 取 #messages 下的 .msg__bubble（流式阶段专用，避免缓存陈旧引用）
function getBubbleByIndex(idx) {
    const wrap = document.getElementById('messages');
    if (!wrap) return null;
    const el = wrap.children[idx];
    if (!el) return null;
    return el.querySelector('.msg__bubble');
}

// 只更新 AI 流式 bubble 的文字和状态类，不动其它消息
function updateAIBubble(idx, m) {
    const bubble = getBubbleByIndex(idx);
    if (!bubble) return;
    bubble.textContent = m.content || '';
    bubble.classList.remove('msg__bubble--loading', 'msg__bubble--streaming', 'msg__bubble--error');
    if (m._status === 'streaming') bubble.classList.add('msg__bubble--streaming');
    else if (m._status === 'error') bubble.classList.add('msg__bubble--error');
}

// 平滑滚到底部（异步，避免 DOM 未布局完就滚）
function scrollToBottom() {
    const wrap = document.getElementById('messages');
    if (!wrap) return;
    requestAnimationFrame(() => {
        wrap.scrollTop = wrap.scrollHeight;
    });
}

// 提到模块级，stopStream 也需要调用
function finishStream() {
    chatState.sending = false;
    chatState.streamAbort = null;
    const btnSend = document.getElementById('btnSend');
    const btnStop = document.getElementById('btnStop');
    const input = document.getElementById('msgInput');
    if (btnSend && input) btnSend.disabled = !input.value.trim();
    if (btnStop) btnStop.hidden = true;
}

function stopStream() {
    if (!chatState.streamAbort) return;
    chatState.streamAbort.abort();  // 真中断 fetch
    // api.stream 内部把 AbortError 静默吞掉，onError 不会触发 → 手动清状态
    const idx = chatState.messages.findIndex(
        m => m._status === 'loading' || m._status === 'streaming'
    );
    if (idx >= 0) {
        const m = chatState.messages[idx];
        m.content = '⏹ 已停止生成';
        m._status = 'done';
        renderMessages();
        scrollToBottom();
    }
    finishStream();
}

// ============ 转人工 / 找教练 ============

async function transferToHuman() {
    if (!chatState.currentConvId) {
        // 没选中会话：新建一个再转人工
        try {
            const conv = await api.post('/conversations', { title: '教练咨询会话' });
            chatState.currentConvId = conv.id;
            chatState.messages = [];
            chatState.currentConvStatus = conv.status;
            renderMessages();
            await loadConversations();
        } catch (e) {
            alert('创建会话失败：' + e.message);
            return;
        }
    }
    try {
        const res = await api.post(`/conversations/${chatState.currentConvId}/transfer`);
        applyConvStatus(res.status);
        // ponytail: 教练兼客服，转人工 = 转教练，统一为"等待教练接入"提示
        if (res.status === 'waiting_trainer' || (res.message && res.message.includes('排队'))) {
            const sysMsg = {
                id: null,
                sender_type: 'system',
                content: '🏋️ 已为你转接教练，请稍候',
                created_at: new Date().toISOString(),
            };
            chatState.messages.push(sysMsg);
            appendMessageDOM(sysMsg);
        }
    } catch (e) {
        alert('转人工失败：' + e.message);
    }
}

async function findTrainer() {
    if (!chatState.currentConvId) {
        // 没选中会话：新建一个再找教练
        try {
            const conv = await api.post('/conversations', { title: '教练咨询' });
            chatState.currentConvId = conv.id;
            chatState.messages = [];
            chatState.currentConvStatus = conv.status;
            renderMessages();
            await loadConversations();
        } catch (e) {
            alert('创建会话失败：' + e.message);
            return;
        }
    }
    try {
        const res = await api.post(`/conversations/${chatState.currentConvId}/transfer-to-trainer`);
        applyConvStatus(res.status);
        // 幂等：已在 waiting_trainer / trainer_active 不重复提示
        if (res.status === 'waiting_trainer' && (!res.message || res.message.includes('排队') || res.message.includes('等待'))) {
            const sysMsg = {
                id: null,
                sender_type: 'system',
                content: '🏋️ 已为你联系教练，请稍候',
                created_at: new Date().toISOString(),
            };
            chatState.messages.push(sysMsg);
            appendMessageDOM(sysMsg);
        }
    } catch (e) {
        alert('找教练失败：' + e.message);
    }
}

async function adoptTemplate(templateId, btn) {
    if (!templateId) return;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 采用中...'; }
    try {
        const plan = await api.post(`/plan-templates/${templateId}/adopt`);
        if (btn) { btn.textContent = '✅ 已采用'; btn.disabled = true; }
        alert(`已为你在"我的计划"中创建《${plan.name || '新计划'}》`);
        // 让用户能看到新计划
        setTimeout(() => {
            if (confirm('是否跳转到我的计划查看？')) {
                window.location.href = `/c/plans.html?focus=${plan.id}`;
            }
        }, 200);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = '✅ 采用为我的计划'; }
        alert('采用失败：' + e.message);
    }
}

// ============ 新建会话 ============

async function newConversation() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const title = `新对话 ${hh}:${mm}`;
    try {
        const conv = await api.post('/conversations', { title });
        chatState.currentConvId = conv.id;
        chatState.messages = [];
        chatState.currentConvStatus = conv.status || 'ai_active';
        document.getElementById('chatTitle').textContent = conv.title;
        renderMessages();
        updateStatusBanner();
        await loadConversations();
    } catch (e) {
        // 401 时 api.js 已经跳转到登录页
        if (e.status !== 401) {
            alert('新建会话失败：' + (e.message || '未知错误'));
        }
    }
}

// ============ 挂载 ============

export function mountChat({ escapeHtml }) {
    esc = escapeHtml || ((s) => String(s ?? ''));

    document.getElementById('btnNewChat').addEventListener('click', () => newConversation());
    document.getElementById('btnSend').addEventListener('click', () => sendMessage());
    document.getElementById('btnStop').addEventListener('click', stopStream);
    document.getElementById('btnTransfer').addEventListener('click', () => transferToHuman());
    document.getElementById('btnFindTrainer').addEventListener('click', () => findTrainer());
    const msgInput = document.getElementById('msgInput');
    msgInput.addEventListener('input', () => {
        document.getElementById('btnSend').disabled = !msgInput.value.trim() || chatState.sending;
        msgInput.style.height = 'auto';
        msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
    });
    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    if (tokenStore.isLoggedIn) {
        loadConversations();
    } else {
        document.querySelector('.chat-messages').innerHTML = `
            <div class="chat-empty">
                <div class="chat-empty__art">🔒</div>
                <div class="chat-empty__title">登录后与 AI 教练对话</div>
                <div class="chat-empty__desc">点击右上角"登录"按钮，或前往 <a href="/c/login.html" style="color: var(--accent-cool-bright);">登录页</a></div>
            </div>
        `;
    }
}
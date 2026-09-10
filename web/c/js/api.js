/**
 * API 调用封装
 *
 * 用法：
 *   import { api } from './api.js';
 *   const data = await api.get('/exercises');
 */

// 后端基础 URL（前后端同源，使用相对路径，自动适配任意端口/域名）
const API_BASE = '/api/v1';

const TOKEN_KEY = 'fithub_access_token';
const REFRESH_KEY = 'fithub_refresh_token';
const USER_KEY = 'fithub_user';

export const tokenStore = {
    get access() { return localStorage.getItem(TOKEN_KEY); },
    get refresh() { return localStorage.getItem(REFRESH_KEY); },
    get user() {
        try { return JSON.parse(localStorage.getItem(USER_KEY)); }
        catch { return null; }
    },
    set(access, refresh, user) {
        localStorage.setItem(TOKEN_KEY, access);
        localStorage.setItem(REFRESH_KEY, refresh);
        localStorage.setItem(USER_KEY, JSON.stringify(user));
    },
    clear() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_KEY);
        localStorage.removeItem(USER_KEY);
    },
    get isLoggedIn() { return !!this.access; },
};

async function request(path, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
    };

    // 自动加 Bearer Token
    if (tokenStore.access) {
        headers['Authorization'] = `Bearer ${tokenStore.access}`;
    }

    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
    const response = await fetch(url, {
        ...options,
        headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
    });

    // 401：先试一次刷新；refresh 也失败则强制登出
    if (response.status === 401 && tokenStore.refresh && !options._isRetry) {
        const refreshed = await tryRefresh();
        if (refreshed) {
            return request(path, { ...options, _isRetry: true });
        }
        // refresh 失败：登出 + 跳登录页
        tokenStore.clear();
        if (!location.pathname.includes('/login.html')) {
            location.href = '/c/login.html?expired=1&next=' + encodeURIComponent(location.pathname + location.search);
        }
        throw new ApiError(401, '登录已过期，请重新登录');
    }

    // 重试后仍是 401：刷新拿到的新 token 也无效 → 直接登出
    if (response.status === 401 && options._isRetry) {
        tokenStore.clear();
        if (!location.pathname.includes('/login.html')) {
            location.href = '/c/login.html?expired=1&next=' + encodeURIComponent(location.pathname + location.search);
        }
        throw new ApiError(401, '登录已过期，请重新登录');
    }

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new ApiError(response.status, error.detail || '请求失败');
    }

    // 204 No Content
    if (response.status === 204) return null;
    return response.json();
}

async function tryRefresh() {
    try {
        const data = await request('/auth/refresh', {
            method: 'POST',
            body: { refresh_token: tokenStore.refresh },
            _isRetry: true,  // 避免无限递归
        });
        tokenStore.set(data.access_token, data.refresh_token, data.user);
        return true;
    } catch {
        return false;
    }
}

/**
 * 流式请求（SSE，POST）。
 *
 * 用法：
 *   const { abort } = api.stream('/chat/send/stream', { content, conversation_id }, (ev) => {
 *       if (ev.type === 'delta') append(ev.text);
 *       else if (ev.type === 'done') finish(ev);
 *   });
 *
 * ponytail: 不做 401 自动刷新（流无法 replay）。调用前自己确保 token 有效。
 *
 * 实现：controller 在调用瞬间就建好并返回 abort()，所以调用方能立刻拿到
 * 真正的中断句柄（避免把 Promise 当 abort 对象用）。fetch 后续在 IIFE 里异步执行。
 */
function stream(path, body, onEvent, onError) {
    const headers = { 'Content-Type': 'application/json' };
    if (tokenStore.access) {
        headers['Authorization'] = `Bearer ${tokenStore.access}`;
    }
    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;

    // 1) 同步建好 controller，立刻返回 abort 句柄
    const controller = new AbortController();

    // 2) fetch + 流解析放在 IIFE 里异步跑
    (async () => {
        let response;
        try {
            response = await fetch(url, {
                method: 'POST',
                headers,
                body: JSON.stringify(body || {}),
                signal: controller.signal,
            });
        } catch (e) {
            if (e.name !== 'AbortError' && onError) onError(e);
            return;
        }

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            const e = new ApiError(response.status, err.detail || '请求失败');
            if (onError) onError(e);
            return;
        }
        if (!response.body) {
            const e = new ApiError(0, '浏览器不支持流式响应');
            if (onError) onError(e);
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                // SSE 规范允许 CRLF / CR / LF 行尾，后端实际发的是 CRLF；
                // 统一归一为 LF，否则 buffer.indexOf('\n\n') 永远匹配不到 \r\n\r\n
                buffer += decoder.decode(value, { stream: true })
                    .replace(/\r\n/g, '\n')
                    .replace(/\r/g, '\n');

                // SSE 事件以 \n\n 分隔
                let sep;
                while ((sep = buffer.indexOf('\n\n')) !== -1) {
                    const raw = buffer.slice(0, sep);
                    buffer = buffer.slice(sep + 2);

                    // 解析 "data: {...}"
                    for (const line of raw.split('\n')) {
                        const trimmed = line.trim();
                        if (!trimmed.startsWith('data:')) continue;
                        const payload = trimmed.slice(5).trim();
                        if (!payload) continue;
                        try {
                            onEvent(JSON.parse(payload));
                        } catch (e) {
                            console.warn('SSE JSON parse error:', e, payload);
                        }
                    }
                }
            }
        } catch (e) {
            // AbortError 静默（调用方主动停止），其它错误回调
            if (e.name !== 'AbortError' && onError) onError(e);
        }
    })();

    return { abort: () => controller.abort() };
}

export class ApiError extends Error {
    constructor(status, message) {
        super(message);
        this.status = status;
    }
}

export const api = {
    get: (path) => request(path, { method: 'GET' }),
    post: (path, body) => request(path, { method: 'POST', body }),
    patch: (path, body) => request(path, { method: 'PATCH', body }),
    delete: (path) => request(path, { method: 'DELETE' }),
    stream,

    // 鉴权
    auth: {
        register: (data) => request('/auth/register', { method: 'POST', body: data }),
        login: (data) => request('/auth/login', { method: 'POST', body: data }),
        me: () => request('/users/me'),
    },

    // 动作
    exercises: {
        list: (params) => {
            const qs = new URLSearchParams(params).toString();
            return request(`/exercises${qs ? '?' + qs : ''}`);
        },
        get: (id) => request(`/exercises/${id}`),
        filters: () => request('/exercises/filters'),
    },
};
// 谭师动作库 — 列表页（多维筛选面板）

// 既支持 export.mount(container) 挂载到任意节点（被 index-tabs.js 调用），

// 也支持在 tan-library.html 直接打开时自启动。



const API = '/api/v1';



const STATE = {

    q: '',                  // 搜索框

    bodyTab: '胸部',        // 一级 Tab（中文 label）

    warmup: false,          // 二级 Tab（true=仅热身）

    muscleGroup: null,      // 肌肉分组 key

    actionType: null,       // 动作类型 key

};



let META = null;             // /meta 缓存

let els = null;              // DOM 引用

let debounceT = null;



// ============ 工具函数 ============

function escapeHtml(s) {

    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({

        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'

    }[c]));

}



function resolveMediaUrl(path) {

    if (!path) return '';

    if (path.startsWith('http://') || path.startsWith('https://')) return path;

    if (path.startsWith('/')) return path;

    return '/c/' + path;

}



function getBodyPartEmoji(bodyPart) {

    const map = {

        '胸': '💪', '背': '🏋️', '肩': '🤸', '手臂': '💪',

        '下肢': '🦵', '躯干': '🧘', '热身与活动度': '🤾',

    };

    return map[bodyPart] || '🏃';

}



// ============ 模板：多维筛选面板 + 卡片网格 ============

function buildTemplate() {

    return `

        <div class="tan-main">

            <div class="content__header">
                <h1 class="content__title">谭师动作库</h1>
                <div class="content__meta" id="tanResultMetaTop">加载中...</div>
            </div>



            <aside class="tan-sidebar">

                <!-- 顶部搜索框 -->

                <div class="tan-sidebar__group">

                    <input id="tanSearch" class="tan-search" type="search"

                           placeholder="搜索动作、器械、肌肉…" autocomplete="off">

                </div>



                <!-- 一级 Tab：身体部位 -->

                <div class="tan-sidebar__group">

                    <div id="tanBodyTabs" class="tan-tabs" role="tablist"></div>

                </div>



                <!-- 二级 Tab：全部 / 热身 -->

                <div class="tan-sidebar__group">

                    <div id="tanWarmupTabs" class="tan-warmup-tabs" role="tablist"></div>

                </div>



                <!-- 横向触发器 + 弹出下拉 -->

                <div class="tan-sidebar__group tan-triggers" id="tanTriggers"></div>



                <!-- 训练计划快捷入口（三分化 / 四分化） -->

                <div class="tan-sidebar__group">

                    <div class="tan-sidebar__label">训练计划</div>

                    <div id="tanPlansList" class="tan-plans-list"></div>

                </div>



                <!-- 饮食专区：触发按钮（点击后右栏显示专题卡） -->

                <div class="tan-sidebar__group">

                    <div class="tan-sidebar__label">饮食</div>

                    <button type="button" id="tanDietTrigger" class="tan-trigger-btn">

                        <span class="tan-plan-item__icon">🍽️</span>

                        <span class="tan-sidebar__label" style="margin:0;flex:1;font-size:12px;">饮食专题</span>

                        <span class="tan-plan-item__arrow">›</span>

                    </button>

                </div>

            </aside>



            <section class="tan-content">

                <div class="content__header">

                    <div class="content__meta" id="tanResultMeta">加载中…</div>

                    <a id="backToList" class="content__back" style="display:none;" href="#">‹ 返回动作列表</a>

                </div>

                <div class="grid" id="tanGrid" aria-live="polite"></div>

                <div id="tanDietDetail" class="tan-diet-detail" style="display:none;"></div>

            </section>

        </div>



        <p class="tan-credit">

            动作示范视频 © 谭成义（@j1exanderspace）

        </p>

    `;

}



// ============ 渲染 meta → UI ============

function renderBodyTabs() {

    const wrap = els.bodyTabs;

    wrap.innerHTML = '';

    META.body_tabs.forEach(t => {

        const btn = document.createElement('button');

        btn.className = 'tan-tab';

        btn.textContent = t.label;

        btn.dataset.label = t.label;

        btn.dataset.body = t.body || '';

        btn.setAttribute('aria-pressed', t.label === STATE.bodyTab ? 'true' : 'false');

        btn.addEventListener('click', () => {

            console.log('[tan] tab clicked:', t.label);

            onBodyTabChange(t.label);

        });

        wrap.appendChild(btn);

    });

}



// 切一级 Tab 时：重置 warmup/muscleGroup、刷新 meta（让 equipments/action_types 按 body 过滤）、重新渲染

async function onBodyTabChange(label) {

    console.log('[tan] onBodyTabChange start, label=', label, 'current bodyTab=', STATE.bodyTab);

    STATE.bodyTab = label;

    STATE.warmup = false;

    closeAllDropdowns();

    console.log('[tan] after closeAllDropdowns, _globalDrop has', _globalDrop ? _globalDrop.children.length : 0, 'children');

    const newGroupKey = BODY_TO_MUSCLE_GROUP[label];

    if (newGroupKey && STATE.muscleGroup && !STATE.muscleGroup.startsWith(newGroupKey + '_')) {

        STATE.muscleGroup = null;

    } else if (!newGroupKey) {

        STATE.muscleGroup = null;

    }

    renderBodyTabs();

    renderWarmupTabs();

    // 重新拉 meta（按 body 过滤 equipments/action_types）

    const tab = META.body_tabs.find(t => t.label === label);

    const bodyParam = tab && tab.body ? `?body=${encodeURIComponent(tab.body)}` : '';

    try {

        META = await fetch(`${API}/tan-actions/meta${bodyParam}`).then(r => r.json());

    } catch (e) {

        console.warn('[tan] meta refetch failed', e);

    }

    renderTriggers();

    await loadList();

}



function renderWarmupTabs() {

    const wrap = els.warmupTabs;

    wrap.innerHTML = '';

    META.warmup_tabs.forEach(t => {

        const btn = document.createElement('button');

        btn.className = 'tan-warmup-tab';

        btn.textContent = t.label;

        const isWarmup = t.key === 'warmup';

        btn.setAttribute('aria-pressed', (isWarmup === STATE.warmup) ? 'true' : 'false');

        btn.addEventListener('click', () => {

            STATE.warmup = isWarmup;

            renderWarmupTabs();

            loadList();

        });

        wrap.appendChild(btn);

    });

}



// 全局浮层：单一 dropdown 容器，3 个触发器共享

let _globalDrop = null;

let _activeTrigger = null;



function getGlobalDrop() {

    if (_globalDrop) return _globalDrop;

    const drop = document.createElement('div');

    drop.className = 'tan-dropdown tan-dropdown--floating';

    document.body.appendChild(drop);

    _globalDrop = drop;

    return drop;

}



function positionDrop(btn) {

    const drop = getGlobalDrop();

    const r = btn.getBoundingClientRect();

    const margin = 6;

    // 先临时定位到屏幕左上角且可见，测真实高度

    drop.style.visibility = 'hidden';

    drop.style.top = '0px';

    drop.style.left = '-9999px';

    drop.style.width = `${r.width}px`;

    drop.classList.add('tan-dropdown--visible');

    const dh = drop.offsetHeight;

    const vh = window.innerHeight;

    // 算最终 top：默认向下，超出底部则向上翻转

    let top = r.bottom + margin;

    if (top + dh > vh - 8) {

        top = Math.max(8, r.top - dh - margin);

    }

    let left = r.left;

    // 水平：超右则改右对齐

    if (left + r.width > window.innerWidth - 8) {

        left = Math.max(8, window.innerWidth - r.width - 8);

    }

    drop.style.top = `${top}px`;

    drop.style.left = `${left}px`;

    drop.style.visibility = '';

}



// 一级 Tab 中文 label → 肌肉组 key 映射

const BODY_TO_MUSCLE_GROUP = {

    '胸部': 'chest',

    '背部': 'back',

    '肩部': 'shoulder',

    '腿臀': 'leg',

    '手臂': 'arm',

    '腹部': 'abs',

    '全身': null,  // 全身不限定

};



// 器械 / 动作类型：按当前一级 Tab 的 body 字段过滤（"全部" 时返回全量）

function getMuscleGroupForBody(bodyTab) {

    const key = BODY_TO_MUSCLE_GROUP[bodyTab];

    if (!key) return null;  // 全身

    return META.muscle_groups.find(g => g.key === key) || null;

}



function renderTriggers() {

    // 用一个 map 缓存已创建的 row，按 trigger key 复用

    if (!renderTriggers._cache) renderTriggers._cache = {};



    // 肌肉组选项：根据当前一级 Tab 过滤

    const currentGroup = getMuscleGroupForBody(STATE.bodyTab);

    const muscleOptions = currentGroup

        ? [

            { key: currentGroup.key, label: currentGroup.label, count: currentGroup.count, level: 0 },

            ...(currentGroup.children || []).map(c => ({ key: c.key, label: c.label, count: c.count, level: 1 })),

        ]

        : META.muscle_groups.flatMap(g => [

            { key: g.key, label: g.label, count: g.count, level: 0 },

            ...(g.children || []).map(c => ({ key: c.key, label: c.label, count: c.count, level: 1 })),

        ]);



    // 三个触发器配置

    const items = [

        {

            key: 'muscle', label: '细分部位', value: STATE.muscleGroup,

            options: muscleOptions,

        },

        { key: 'equip',  label: '器械',     value: null,

          options: META.equipments.map(e => ({ key: e, label: e, count: null, level: 0 })) },

        { key: 'action', label: '动作类型', value: STATE.actionType,

          options: META.action_types.map(t => ({ key: t.key, label: t.label, count: t.count, level: 0 })) },

    ];



    const wrap = els.triggers;

    items.forEach(it => {

        let row = renderTriggers._cache[it.key];

        if (!row) {

            // 首次创建

            row = document.createElement('div');

            row.className = 'tan-trigger';

            const btn = document.createElement('button');

            btn.className = 'tan-trigger__btn';

            row.appendChild(btn);

            wrap.appendChild(row);

            renderTriggers._cache[it.key] = row;



            btn.addEventListener('click', (e) => {

                e.stopPropagation();

                const drop = getGlobalDrop();

                if (_activeTrigger === row) {

                    closeAllDropdowns();

                    return;

                }

                closeAllDropdowns();

                // 实时按当前 bodyTab 算 muscle 触发器的 options（不用闭包旧 it）

                const opts = it.key === 'muscle'

                    ? (() => {

                        const g = getMuscleGroupForBody(STATE.bodyTab);

                        return g

                            ? [

                                { key: g.key, label: g.label, count: g.count, level: 0 },

                                ...(g.children || []).map(c => ({ key: c.key, label: c.label, count: c.count, level: 1 })),

                            ]

                            : META.muscle_groups.flatMap(g => [

                                { key: g.key, label: g.label, count: g.count, level: 0 },

                                ...(g.children || []).map(c => ({ key: c.key, label: c.label, count: c.count, level: 1 })),

                            ]);

                    })()

                    : it.options;

                populateDropdown(drop, { ...it, options: opts }, btn);

                positionDrop(btn);

                _activeTrigger = row;

                row.classList.add('tan-trigger--open');

            });

        }

        // 更新按钮文本（基于当前 STATE）

        const btn = row.firstChild;

        const selected = it.value ? it.options.find(o => o.key === it.value) : null;

        btn.innerHTML = `

            <span>${escapeHtml(it.label)}</span>

            <span class="tan-trigger__val">${selected ? escapeHtml(selected.label) : '全部'}</span>

            <span class="tan-trigger__arrow">▾</span>

        `;

    });

}



function populateDropdown(drop, it, anchorBtn) {

    drop.innerHTML = '';

    if (it.key === 'equip') {

        const sub = document.createElement('input');

        sub.className = 'tan-dropdown__search';

        sub.placeholder = '搜索器械…';

        sub.addEventListener('input', () => {

            const kw = sub.value.trim().toLowerCase();

            drop.querySelectorAll('.tan-dropdown__item').forEach(li => {

                li.style.display = li.textContent.toLowerCase().includes(kw) ? '' : 'none';

            });

        });

        drop.appendChild(sub);

    }

    // "全部"

    const allItem = document.createElement('div');

    allItem.className = 'tan-dropdown__item tan-dropdown__item--top' + (it.value == null ? ' is-selected' : '');

    allItem.innerHTML = `<span class="tan-dropdown__label">全部</span>`;

    allItem.addEventListener('click', () => {

        if (it.key === 'muscle') STATE.muscleGroup = null;

        if (it.key === 'action') STATE.actionType = null;

        closeAllDropdowns();

        renderTriggers();

        loadList();

    });

    drop.appendChild(allItem);



    it.options.forEach(opt => {

        const li = document.createElement('div');

        li.className = 'tan-dropdown__item'

            + (opt.level === 1 ? ' tan-dropdown__item--child' : '')

            + (it.value === opt.key ? ' is-selected' : '');

        const hint = opt.hint ? ` <span class="tan-dropdown__hint">(${escapeHtml(opt.hint)})</span>` : '';

        li.innerHTML = `

            <span class="tan-dropdown__check">${it.value === opt.key ? '✓' : ''}</span>

            <span class="tan-dropdown__label">${opt.level === 1 ? '└ ' : ''}${escapeHtml(opt.label)}${hint}</span>

            ${opt.count != null ? `<span class="tan-dropdown__count">${opt.count}</span>` : ''}

        `;

        li.addEventListener('click', (e) => {

            e.stopPropagation();

            if (it.key === 'muscle') STATE.muscleGroup = opt.key;

            if (it.key === 'action') STATE.actionType = opt.key;

            closeAllDropdowns();

            renderTriggers();

            loadList();

        });

        drop.appendChild(li);

    });

}



function closeAllDropdowns() {

    if (_globalDrop) {

        _globalDrop.classList.remove('tan-dropdown--visible');

        _globalDrop.innerHTML = '';

    }

    if (_activeTrigger) {

        _activeTrigger.classList.remove('tan-trigger--open');

        _activeTrigger = null;

    }

}



// ============ 数据加载 ============

async function loadMeta() {

    const r = await fetch(`${API}/tan-actions/meta`);

    if (!r.ok) throw new Error(`/tan-actions/meta ${r.status}`);

    return r.json();

}



function renderCard(a) {

    const card = document.createElement('a');

    card.href = `tan-guide.html?id=${encodeURIComponent(a.id)}`;

    card.className = 'card';

    const thumb = a.thumbnail ? resolveMediaUrl(a.thumbnail) : '';

    const placeholder = getBodyPartEmoji(a.body);

    card.innerHTML = `

        <div class="card__image-wrap" style="background:linear-gradient(135deg, ${placeholder === '💪' ? '#fee2e2' : '#e0e7ff'} 0%, #f3f4f6 100%);">

            ${thumb

                ? `<img class="card__image" src="${escapeHtml(thumb)}" alt="${escapeHtml(a.name)}" loading="lazy"

                     onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">`

                : ''}

            <div class="card__image-placeholder" style="${thumb ? 'display:none;' : ''}">${placeholder}</div>

        </div>

        <div class="card__body">

            <div class="card__name-zh">${escapeHtml(a.name)}</div>

            <div class="card__name-en" style="color:var(--text-muted);font-size:12px;">${escapeHtml(a.body)} · ${escapeHtml((a.equipment || [])[0] || '—')}</div>

            <div class="card__tags">

                <span class="tag">${escapeHtml(a.body || '—')}</span>

                <span class="tag">${escapeHtml((a.equipment || [])[0] || '—')}</span>

            </div>

        </div>

    `;

    return card;

}



function renderEmpty() {

    els.grid.innerHTML = '';

    const empty = document.createElement('div');

    empty.className = 'tan-empty';

    empty.style.gridColumn = '1 / -1';

    empty.innerHTML = `<b>没找到匹配的动作</b><br><span style="color:var(--muted);">试试别的关键字，或清空筛选</span>`;

    els.grid.appendChild(empty);

}



function renderError(msg) {

    els.grid.innerHTML = '';

    const err = document.createElement('div');

    err.className = 'tan-empty';

    err.style.gridColumn = '1 / -1';

    err.style.color = 'var(--primary)';

    err.innerHTML = `<b>😢 加载失败</b><br><span style="color:var(--muted);font-size:12px;">${escapeHtml(msg)}</span><br>

        <button onclick="location.reload()" style="margin-top:14px;padding:6px 18px;border-radius:8px;background:var(--primary);color:#fff;border:none;cursor:pointer;">重试</button>`;

    els.grid.appendChild(err);

}



function renderLoading() {

    els.grid.innerHTML = '';

    const div = document.createElement('div');

    div.className = 'tan-empty';

    div.style.gridColumn = '1 / -1';

    div.innerHTML = `<span style="color:var(--muted);">加载中…</span>`;

    els.grid.appendChild(div);

}



async function loadList() {

    renderLoading();

    try {

        const params = new URLSearchParams();

        if (STATE.warmup) {

            params.set('warmup', 'true');

        } else {

            const tab = META.body_tabs.find(t => t.label === STATE.bodyTab);

            if (tab && tab.body) params.set('body', tab.body);

        }

        if (STATE.muscleGroup) params.set('muscle_group', STATE.muscleGroup);

        if (STATE.actionType) params.set('action_type', STATE.actionType);

        if (STATE.q) params.set('q', STATE.q);

        params.set('limit', '60');

        const r = await fetch(`${API}/tan-actions?${params}`);

        if (!r.ok) throw new Error(`/tan-actions ${r.status}`);

        const d = await r.json();

        els.resultMetaTop.textContent = `共 ${d.total} 个动作`;
        els.resultMeta.textContent = `共 ${d.total} 个动作`;

        if (!d.items || d.items.length === 0) {

            renderEmpty();

            return;

        }

        els.grid.innerHTML = '';

        d.items.forEach(a => els.grid.appendChild(renderCard(a)));

    } catch (e) {

        renderError(e.message || String(e));

    }

}



// ============ Mount ============

// ============ 训练计划列表（侧边栏） ============

async function loadAndRenderPlans() {

    if (!els.plansList) return;

    try {

        const r = await fetch(`${API}/tan-plans`);

        if (!r.ok) throw new Error(`HTTP ${r.status}`);

        const d = await r.json();

        renderPlans(d.plans || []);

    } catch (e) {

        console.warn('[tan] load plans failed', e);

        els.plansList.innerHTML = '<div style="font-size:11px;color:var(--muted);">计划加载失败</div>';

    }

}



function renderPlans(plans) {

    if (!els.plansList) return;

    els.plansList.innerHTML = '';

    const iconMap = { '三分化': '🔥', '四分化': '💪' };

    plans.forEach(p => {

        const item = document.createElement('a');

        item.className = 'tan-plan-item';

        item.href = `tan-plan.html?name=${encodeURIComponent(p.name)}`;

        item.innerHTML = `

            <span class="tan-plan-item__icon">${iconMap[p.name] || '📋'}</span>

            <div class="tan-plan-item__main">

                <div class="tan-plan-item__name">${escapeHtml(p.name)}</div>

                <div class="tan-plan-item__meta">${p.days_count}天 / ${p.total_actions}动作</div>

            </div>

            <span class="tan-plan-item__arrow">›</span>

        `;

        els.plansList.appendChild(item);

    });

}



async function loadAndRenderDiet() {

    if (!els.dietTrigger) return;

    // 缓存主题数据，点击触发按钮时渲染右栏专题卡片网格

    let _topics = null;

    async function fetchTopics() {

        if (_topics) return _topics;

        const r = await fetch(`${API}/tan-diet`);

        if (!r.ok) throw new Error(`HTTP ${r.status}`);

        const d = await r.json();

        _topics = d.topics || [];

        return _topics;

    }

    els.dietTrigger.addEventListener('click', async () => {

        try {

            const topics = await fetchTopics();

            showDietTopics(topics);

        } catch (e) {

            console.warn('[tan] load diet failed', e);

        }

    });

}



// 右栏内联展示：饮食原理与计算（10 模块）

function showDietTopics(topics) {

    if (!els.grid || !els.dietDetail) return;

    els.grid.style.display = 'none';

    if (els.resultMeta) els.resultMeta.style.display = 'none';

    if (els.backToList) els.backToList.style.display = '';

    els.dietDetail.innerHTML = '';



    // 分隔 + 饮食原理标题

    const divider = document.createElement('div');
    divider.className = 'tan-diet-divider';
    divider.innerHTML = `<span>📋 饮食原理与计算</span>`;
    els.dietDetail.appendChild(divider);

    // 内联饮食原理 10 模块

    const principle = document.createElement('div');
    principle.className = 'tan-diet-principle';
    principle.innerHTML = DIET_PRINCIPLE_HTML;
    els.dietDetail.appendChild(principle);



    // 绑定折叠面板

    principle.querySelectorAll('[data-collapse]').forEach(el => {

        const head = el.querySelector('[data-toggle]');

        if (head) head.addEventListener('click', () => el.classList.toggle('is-open'));

    });



    // 绑定计算按钮

    const calcBtn = principle.querySelector('#calcBtn');

        loadAndFillDietVideos(principle);

    if (calcBtn) calcBtn.addEventListener('click', () => runDietCalc(principle));

    // 绑定"使用示例数据"按钮：男 / 23 / 68 / 173 / 减脂 / 2-3
    const fillBtn = principle.querySelector('#fillExampleBtn');
    if (fillBtn) fillBtn.addEventListener('click', () => {
        const $ = id => principle.querySelector('#' + id);
        const set = (id, v) => { const el = $(id); if (el) el.value = v; };
        set('gender', 'male');
        set('age', '23');
        set('weight', '68');
        set('height', '173');
        set('goal', 'cut');
        set('hours', '2-3');
        fillBtn.style.display = 'none';
    });



    // 绑定 meat toggle / egg select

    principle.querySelectorAll('#meatToggle button').forEach(btn => {

        btn.addEventListener('click', () => {

            principle.querySelectorAll('#meatToggle button').forEach(b => b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'));

            runDietCalc(principle);

        });

    });

    const eggSelect = principle.querySelector('#eggCount');

    if (eggSelect) eggSelect.addEventListener('change', () => runDietCalc(principle));



    els.dietDetail.style.display = 'block';

}



function hideDietDetail() {

    if (!els.grid || !els.dietDetail || !els.backToList) return;

    els.dietDetail.style.display = 'none';

    els.backToList.style.display = 'none';

    els.grid.style.display = '';

    els.resultMeta.style.display = '';

}



async function mount(container) {

    container.innerHTML = buildTemplate();

    els = {

        search: container.querySelector('#tanSearch'),

        bodyTabs: container.querySelector('#tanBodyTabs'),

        warmupTabs: container.querySelector('#tanWarmupTabs'),

        triggers: container.querySelector('#tanTriggers'),

        plansList: container.querySelector('#tanPlansList'),

        dietTrigger: container.querySelector('#tanDietTrigger'),

        grid: container.querySelector('#tanGrid'),

        dietDetail: container.querySelector('#tanDietDetail'),

        backToList: container.querySelector('#backToList'),

        resultMeta: container.querySelector('#tanResultMeta'),

        resultMetaTop: container.querySelector('#tanResultMetaTop'),

    };

    els.search.addEventListener('input', () => {

        clearTimeout(debounceT);

        debounceT = setTimeout(() => {

            STATE.q = els.search.value.trim();

            loadList();

        }, 250);

    });

    if (els.backToList) {

        els.backToList.addEventListener('click', (e) => {

            e.preventDefault();

            hideDietDetail();

        });

    }

    // 点击空白关闭下拉（下拉自身 click 不算空白）

    document.addEventListener('click', (e) => {

        if (_globalDrop && _globalDrop.contains(e.target)) return;

        closeAllDropdowns();

    });

    // ESC 关闭

    document.addEventListener('keydown', (e) => {

        if (e.key === 'Escape') closeAllDropdowns();

    });

    // 滚动时关闭（但下拉面板自身滚动不触发）

    window.addEventListener('scroll', (e) => {

        if (_globalDrop && _globalDrop.contains(e.target)) return;

        closeAllDropdowns();

    }, true);

    window.addEventListener('resize', closeAllDropdowns);

    try {

        META = await loadMeta();

        els.resultMetaTop.textContent = `共 ${META.count} 个动作`;

        renderBodyTabs();

        renderWarmupTabs();

        renderTriggers();

        await loadAndRenderPlans();

        await loadAndRenderDiet();

    } catch (e) {

        renderError(e.message);

        return;

    }

    await loadList();

}



export { mount };



// 自启动

if (typeof document !== 'undefined') {

    const start = () => {

        const r = document.getElementById('tanRoot');

        if (r) mount(r);

    };

    if (document.readyState === 'loading') {

        document.addEventListener('DOMContentLoaded', start);

    } else {

        start();

    }

}



// ============ 饮食原理与计算 HTML（10 模块）============

const DIET_PRINCIPLE_HTML = `
<style>
.diet-page { max-width: 960px; margin: 0 auto; padding: 0 var(--space-5); }
.diet-section { margin-top: var(--space-7); padding: var(--space-5); background: rgba(18, 18, 28, 0.6); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); }
.diet-section h2 { margin: 0 0 8px; color: var(--white); font-size: 22px; }
.diet-section__num { color: var(--primary); margin-right: 8px; }
.diet-section__desc { color: var(--muted); font-size: 13px; line-height: 1.7; margin: 0 0 var(--space-4); }
.diet-form { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-4); margin: var(--space-4) 0; }
.diet-form__col { display: flex; flex-direction: column; gap: var(--space-3); }
.diet-form__field { display: flex; flex-direction: column; gap: 6px; }
.diet-form__field label { font-size: 12px; color: var(--muted); font-weight: 500; }
.diet-form__field input, .diet-form__field select { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border-subtle); background: rgba(0, 0, 0, 0.3); color: var(--white); font-size: 14px; transition: border-color 0.15s, background 0.15s; }
.diet-form__field input:focus, .diet-form__field select:focus { outline: none; border-color: var(--primary); background: rgba(0, 0, 0, 0.45); }
.diet-form__field input::placeholder { color: var(--text-faint); }
.diet-form__field select { appearance: none; -webkit-appearance: none; cursor: pointer; background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888' d='M6 8L2 4h8z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 32px; }
.diet-form__select-wrap { position: relative; }
.diet-form__input-wrap { position: relative; }
.diet-form__input-wrap input { width: 100%; padding-right: 36px; box-sizing: border-box; }
.diet-form__suffix { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: var(--text-faint); font-size: 12px; pointer-events: none; }
.diet-form__actions { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-3); flex-wrap: wrap; }
.diet-form__btn { padding: 10px 24px; border-radius: 8px; background: linear-gradient(135deg, var(--primary), var(--primary-deep)); color: var(--white); border: none; cursor: pointer; font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 8px; transition: box-shadow 0.15s, transform 0.15s; }
.diet-form__btn:hover { box-shadow: 0 4px 16px var(--primary-glow); transform: translateY(-1px); }
.diet-form__arrow { display: inline-block; transition: transform 0.15s; }
.diet-form__btn:hover .diet-form__arrow { transform: translateX(3px); }
.diet-form__btn-link { background: none; border: none; color: var(--accent-cool); font-size: 12px; cursor: pointer; padding: 4px 6px; text-decoration: underline; text-underline-offset: 3px; }
.diet-form__btn-link:hover { color: var(--white); }
.diet-form__note { font-size: 12px; color: var(--text-faint); margin-top: var(--space-3); line-height: 1.7; }
.diet-form__disclaimer { font-size: 11px; color: var(--text-faint); margin-top: var(--space-3); line-height: 1.7; padding-top: var(--space-3); border-top: 1px dashed var(--border-subtle); }
.diet-result { display: none; }
.diet-result.is-shown { display: block; }
.diet-result__params { padding: 8px 12px; background: rgba(0, 0, 0, 0.2); border-radius: 6px; font-size: 12px; color: var(--muted); margin-bottom: var(--space-3); }
.diet-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); margin: var(--space-3) 0; }
.diet-card { padding: var(--space-4); background: rgba(28, 33, 72, 0.5); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); text-align: center; }
.diet-card__label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.diet-card__value { font-size: 32px; font-weight: 700; color: var(--primary); }
.diet-card__unit { font-size: 14px; color: var(--muted); margin-left: 4px; font-weight: normal; }
.diet-card__formula { font-size: 11px; color: var(--text-faint); margin-top: 8px; font-family: monospace; }
.diet-energy { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: rgba(28, 33, 72, 0.5); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); margin: var(--space-3) 0; }
.diet-energy__label { color: var(--muted); font-size: 13px; }
.diet-energy__value { color: var(--white); font-size: 22px; font-weight: 700; }
.diet-bar { display: flex; height: 28px; border-radius: 6px; overflow: hidden; background: rgba(0, 0, 0, 0.3); margin: var(--space-3) 0; }
.diet-bar__seg { display: flex; align-items: center; justify-content: center; color: var(--white); font-size: 11px; font-weight: 600; transition: width 0.3s; }
.diet-bar__seg--carb { background: linear-gradient(135deg, var(--primary), var(--primary-deep)); }
.diet-bar__seg--prot { background: linear-gradient(135deg, var(--accent-cool), var(--accent-purple)); }
.diet-bar__seg--fat { background: linear-gradient(135deg, #fbbf24, #f59e0b); }
.diet-bar__legend { display: flex; gap: var(--space-3); font-size: 11px; color: var(--muted); }
.diet-bar__legend span::before { content: '\u25CF'; margin-right: 4px; }
.diet-warn { padding: 12px 16px; background: rgba(220, 38, 38, 0.15); border: 1px solid rgba(220, 38, 38, 0.4); border-radius: 8px; color: #fca5a5; font-size: 12px; line-height: 1.6; margin: var(--space-3) 0; }
.diet-collapse { border: 1px solid var(--border-subtle); border-radius: 8px; margin: var(--space-3) 0; overflow: hidden; }
.diet-collapse__head { padding: 12px 16px; background: rgba(28, 33, 72, 0.5); cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; }
.diet-collapse__head h3 { margin: 0; color: var(--white); font-size: 15px; }
.diet-collapse__head span { color: var(--primary); transition: transform 0.2s; }
.diet-collapse.is-open .diet-collapse__head span { transform: rotate(180deg); }
.diet-collapse__body { display: none; padding: var(--space-4); background: rgba(18, 18, 28, 0.5); font-size: 13px; line-height: 1.7; color: var(--muted); }
.diet-collapse.is-open .diet-collapse__body { display: block; }
.diet-table { width: 100%; border-collapse: collapse; font-size: 13px; margin: var(--space-3) 0; }
.diet-table th, .diet-table td { padding: 8px 10px; border: 1px solid var(--border-subtle); text-align: center; }
.diet-table th { background: rgba(28, 33, 72, 0.6); color: var(--muted); font-weight: 600; }
.diet-table a { color: var(--accent-cool); text-decoration: none; }
.diet-toggle { display: flex; gap: 8px; margin: var(--space-3) 0; }
.diet-toggle button { padding: 6px 16px; border-radius: 999px; border: 1px solid var(--border-subtle); background: rgba(18, 18, 28, 0.5); color: var(--muted); font-size: 12px; cursor: pointer; }
.diet-toggle button[aria-pressed="true"] { background: linear-gradient(135deg, var(--primary), var(--primary-deep)); color: var(--white); border-color: var(--primary); }
.diet-list { padding-left: 20px; color: var(--muted); font-size: 13px; line-height: 1.9; }
.diet-list b { color: var(--white); }
.diet-tip { font-size: 12px; color: var(--text-faint); line-height: 1.7; margin-top: var(--space-2); }
.tan-diet-divider { display: flex; align-items: center; justify-content: center; margin: var(--space-5) 0 var(--space-3); color: var(--accent-cool); font-size: 14px; font-weight: 600; }
.tan-diet-divider::before, .tan-diet-divider::after { content: ''; flex: 1; height: 1px; background: var(--border-base); margin: 0 12px; }
.diet-video-card { display: flex; gap: 12px; align-items: flex-start; padding: 14px; margin: var(--space-3) 0; background: linear-gradient(135deg, rgba(255,122,69,0.06) 0%, rgba(77,208,255,0.04) 100%); border: 1px solid var(--border-base); border-radius: 10px; }
.diet-video-card__icon { font-size: 28px; flex-shrink: 0; }
.diet-video-card__main { flex: 1; min-width: 0; }
.diet-video-card__title { color: var(--white); font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.diet-video-card__meta { color: var(--accent-cool); font-size: 11px; margin-bottom: 6px; }
.diet-video-card__desc { color: var(--muted); font-size: 12px; line-height: 1.6; margin-bottom: 8px; }
.diet-video-card__watch { display: inline-block; padding: 5px 12px; background: linear-gradient(135deg, var(--primary), var(--primary-deep)); color: var(--white); border-radius: 999px; font-size: 11px; text-decoration: none; }
</style>

<div class="diet-hero" style="margin-bottom:var(--space-4);">
    <h2 style="margin:0 0 12px;font-size:24px;color:var(--white);">饮食｜饮食原理与计算</h2>
    <p style="color:var(--muted);font-size:13px;line-height:1.7;margin:0;">谭成义的减脂方法：先确定每天的碳水、蛋白质和脂肪，再用连续 7–10 天的变化调整。</p>
</div>

<!-- 模块 1：每日摄入计算 -->
<section class="diet-section">
    <h2><span class="diet-section__num">01 /</span> 计算 · 每日摄入计算</h2>
    <p class="diet-section__desc">体重填公斤，运动量按每周实际小时填写。</p>
    <form id="dietForm" onsubmit="return false">
        <div class="diet-form">
            <div class="diet-form__col">
                <div class="diet-form__field">
                    <label for="gender">性别</label>
                    <div class="diet-form__select-wrap">
                        <select id="gender">
                            <option value="" disabled selected hidden>请选择</option>
                            <option value="male">男</option>
                            <option value="female">女</option>
                        </select>
                    </div>
                </div>
                <div class="diet-form__field">
                    <label for="age">年龄</label>
                    <div class="diet-form__input-wrap">
                        <input id="age" type="number" min="10" max="100" placeholder="周岁">
                        <span class="diet-form__suffix">岁</span>
                    </div>
                </div>
                <div class="diet-form__field">
                    <label for="goal">当前目标</label>
                    <div class="diet-form__select-wrap">
                        <select id="goal">
                            <option value="cut" selected>减脂</option>
                            <option value="maintain">维持</option>
                            <option value="bulk">增肌</option>
                        </select>
                    </div>
                </div>
            </div>
            <div class="diet-form__col">
                <div class="diet-form__field">
                    <label for="weight">体重</label>
                    <div class="diet-form__input-wrap">
                        <input id="weight" type="number" min="30" max="200" step="0.1" placeholder="填写体重">
                        <span class="diet-form__suffix">kg</span>
                    </div>
                </div>
                <div class="diet-form__field">
                    <label for="height">身高</label>
                    <div class="diet-form__input-wrap">
                        <input id="height" type="number" min="100" max="220" placeholder="估算代谢时填">
                        <span class="diet-form__suffix">cm</span>
                    </div>
                </div>
                <div class="diet-form__field">
                    <label for="hours">每周运动时长</label>
                    <div class="diet-form__select-wrap">
                        <select id="hours">
                            <option value="" disabled selected hidden>请选择档位</option>
                            <option value="0-1">0-1 小时</option>
                            <option value="2-3">2-3 小时</option>
                            <option value="4-5">4-5 小时</option>
                            <option value="6-8">6-8 小时</option>
                            <option value="8+">8 小时以上</option>
                        </select>
                    </div>
                </div>
            </div>
        </div>
        <p class="diet-form__note">原片按小时分档，训练次数不直接代入。身高仅用于下方的静息代谢估算。</p>
        <div class="diet-form__actions">
            <button class="diet-form__btn" id="calcBtn" type="button">计算参考量 <span class="diet-form__arrow">→</span></button>
            <button class="diet-form__btn-link" id="fillExampleBtn" type="button">使用示例数据</button>
        </div>
        <p class="diet-form__disclaimer">适用于普通健康成年人。孕哺期、进食障碍或需要医疗饮食管理时，请先由专业人员评估。</p>
    </form><div class="diet-video-slot" data-topic="new-plan"></div></section>

<!-- 模块 2 -->
<section class="diet-section diet-result" id="resultSection">
    <p class="diet-result__params" id="resultParams"></p>
    <h2>减脂起始参考</h2>
    <p class="diet-section__desc">每天的三项克数，来自原片系数表。</p>
    <div class="diet-cards">
        <div class="diet-card"><div class="diet-card__label">碳水</div><div><span class="diet-card__value" id="carbG">—</span><span class="diet-card__unit">g</span></div><div class="diet-card__formula" id="carbF">—</div></div>
        <div class="diet-card"><div class="diet-card__label">蛋白质</div><div><span class="diet-card__value" id="protG">—</span><span class="diet-card__unit">g</span></div><div class="diet-card__formula" id="protF">—</div></div>
        <div class="diet-card"><div class="diet-card__label">脂肪</div><div><span class="diet-card__value" id="fatG">—</span><span class="diet-card__unit">g</span></div><div class="diet-card__formula" id="fatF">—</div></div>
    </div>
    <div class="diet-energy"><div class="diet-energy__label">三项折算能量</div><div><span class="diet-energy__value" id="totalKcal">—</span> kcal/天</div></div>
    <div class="diet-bar" id="dietBar">
        <div class="diet-bar__seg diet-bar__seg--carb" id="barCarb" style="width:50%">碳水 50%</div>
        <div class="diet-bar__seg diet-bar__seg--prot" id="barProt" style="width:30%">蛋白 30%</div>
        <div class="diet-bar__seg diet-bar__seg--fat" id="barFat" style="width:20%">脂肪 20%</div>
    </div>
    <div class="diet-bar__legend"><span class="l-carb">碳水</span><span class="l-prot">蛋白质</span><span class="l-fat">脂肪</span></div>
    <p class="diet-section__desc" style="margin-top:var(--space-3);">占比按供能计算：碳水、蛋白质每克约 4 kcal，脂肪每克约 9 kcal。</p>
    <div class="diet-warn" id="dietWarn" style="display:none;">⚠ 表内三项折算能量低于你的静息代谢估算。请先核对输入及适用性。</div>
    <div class="diet-collapse" data-collapse>
        <div class="diet-collapse__head" data-toggle><h3>原片系数与 85 公斤算例</h3><span>▾</span></div>
        <div class="diet-collapse__body">
            <p>男性每周 2-3 小时训练：碳水 = 体重 × 2.2、蛋白 = 体重 × 1.4、脂肪 = 体重 × 0.8。</p>
            <p>85 公斤参考：碳水 ≈ 187g、蛋白 ≈ 119g、脂肪 ≈ 68g。总能量 ≈ 1992 kcal。</p>
        </div>
    </div>
</section>

<!-- 模块 3 -->
<section class="diet-section">
    <h2>食物份量换算</h2>
    <p class="diet-section__desc">以下是全天参考量的等效对照。</p>
    <div class="diet-card" style="text-align:left;margin-bottom:var(--space-3);">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div><div class="diet-card__label" style="text-align:left;">碳水目标</div><div><span class="diet-card__value" id="carbG2" style="font-size:24px;">—</span> <span class="diet-card__unit">g</span></div></div>
            <div style="text-align:right;"><div class="diet-card__label" style="text-align:right;">≈ 熟米饭</div><div><span class="diet-card__value" id="riceG" style="font-size:24px;">—</span> <span class="diet-card__unit">g</span></div></div>
        </div>
        <p class="diet-tip">📌 本页按 150g/碗计算。一碗约 43g 碳水，约 3.6g 蛋白质。</p>
    </div>
    <h3 style="color:var(--white);font-size:15px;margin:var(--space-4) 0 8px;">蛋白质来源换算</h3>
    <table class="diet-table">
        <thead><tr><th>食物</th><th>目标 (g)</th><th>需要 (g)</th><th>自带脂肪 (g)</th></tr></thead>
        <tbody>
            <tr><td>鸡胸肉（熟·去皮去骨）</td><td id="protRow1T">—</td><td id="protRow1G">—</td><td>≈ 3g/100g</td></tr>
            <tr><td>鸡腿肉（大腿部·熟·去皮去骨）</td><td id="protRow2T">—</td><td id="protRow2G">—</td><td>≈ 8g/100g</td></tr>
            <tr><td>水煮鸡蛋（全蛋·去壳）</td><td id="protRow3T">—</td><td id="protRow3G">—</td><td>≈ 5g/个（≈50g）</td></tr>
        </tbody>
    </table>
</section>

<!-- 模块 4 -->
<section class="diet-section">
    <h2>组合换算：米饭 + 鸡肉 + 鸡蛋</h2>
    <p class="diet-section__desc">三类食物的组合演算，扣除米饭和鸡蛋蛋白质。</p>
    <div class="diet-toggle" id="meatToggle">
        <button data-meat="breast" aria-pressed="true">鸡胸肉</button>
        <button data-meat="thigh" aria-pressed="false">鸡腿肉</button>
    </div>
    <div class="diet-form__field" style="max-width:200px;margin-top:var(--space-2);">
        <label>鸡蛋数（个）</label>
        <select id="eggCount">
            <option value="0">0</option><option value="1" selected>1</option><option value="2">2</option><option value="3">3</option>
        </select>
    </div>
    <div class="diet-cards" id="comboOut" style="margin-top:var(--space-3);">
        <div class="diet-card"><div class="diet-card__label">熟米饭</div><div><span class="diet-card__value" id="outRice">—</span><span class="diet-card__unit">g</span></div></div>
        <div class="diet-card"><div class="diet-card__label" id="outMeatLabel">鸡胸肉熟重</div><div><span class="diet-card__value" id="outMeat">—</span><span class="diet-card__unit">g</span></div></div>
        <div class="diet-card"><div class="diet-card__label">水煮鸡蛋</div><div><span class="diet-card__value" id="outEgg">—</span><span class="diet-card__unit">个</span></div></div>
    </div>
    <h3 style="color:var(--white);font-size:15px;margin:var(--space-4) 0 8px;">脂肪补充参考</h3>
    <p class="diet-section__desc" id="fatNote">—</p>
    <div class="diet-video-slot" data-topic="daily-log"></div>
</section>

<!-- 模块 5+6 -->
<section class="diet-section">
    <div class="diet-collapse" data-collapse>
        <div class="diet-collapse__head" data-toggle><h3>份量口径与食物成分来源（USDA）</h3><span>▾</span></div>
        <div class="diet-collapse__body">
            <p>USDA FoodData Central 的每 100g 可食部分数据。</p>
            <table class="diet-table">
                <thead><tr><th>食物</th><th>碳水 (g/100g)</th><th>蛋白质 (g/100g)</th><th>脂肪 (g/100g)</th></tr></thead>
                <tbody><tr><td>熟米饭</td><td>28.2</td><td>2.7</td><td>0.3</td></tr><tr><td>鸡胸肉（熟）</td><td>0</td><td>33.4</td><td>2.7</td></tr><tr><td>鸡腿肉（大腿部·熟）</td><td>0</td><td>28.7</td><td>8.0</td></tr><tr><td>水煮鸡蛋（全蛋）</td><td>1.1</td><td>12.6</td><td>10.6</td></tr></tbody>
            </table>
        </div>
    </div>
    <div class="diet-collapse" data-collapse>
        <div class="diet-collapse__head" data-toggle><h3>静息代谢估算（Mifflin-St Jeor）</h3><span>▾</span></div>
        <div class="diet-collapse__body">
            <p>男性：10 × 体重 + 6.25 × 身高 − 5 × 年龄 + 5</p>
            <p>女性：10 × 体重 + 6.25 × 身高 − 5 × 年龄 − 161</p>
        </div>
    </div>
</section>

<!-- 模块 7 -->
<section class="diet-section">
    <h2><span class="diet-section__num">02 /</span> 原理 · 谭成义饮食原理</h2>
    <ol class="diet-list">
        <li><b>01 起始摄入量：</b>根据当前体重和每周运动时长，分别算出三大营养素。</li>
        <li><b>02 连续变化与身体状态：</b>先执行 7–10 天，记录体重，约每 10 天拍一次对比照。</li>
        <li><b>03 碳水调整与复评：</b>进展满意就保持；下降过快可考虑增加一些碳水，过慢可考虑减少。</li>
        <li><b>04 食物组成与日常搭配：</b>原片强调先学会认识食物成分，再逐渐形成日常吃法。</li>
    </ol>
</section>

<!-- 模块 8 -->
<section class="diet-section">
    <h2>三餐搭配示例</h2>
    <div class="diet-video-slot" data-topic="cut-meal"></div>
    <p class="diet-section__desc">以下是基础篇的食物结构，份量要按自己的参考量安排。</p>    <div class="diet-meal">
        <div class="diet-meal__item"><b>早餐</b>燕麦 + 鸡蛋，搭配水果；坚果或种子计入当天摄入。</div>
        <div class="diet-meal__item"><b>午餐</b>米饭 + 鱼、鸡肉或虾仁 + 蔬菜。</div>
        <div class="diet-meal__item"><b>晚餐</b>薯类等主食 + 牛肉等蛋白质食物 + 蔬菜。</div>
    </div>
    <p class="diet-tip">📌 同样 100 克，不同食材的营养量并不相同。精确记录优先看食品标签，区分生重、熟重和可食部分，也算入油与酱料。</p><div class="diet-video-slot" data-topic="rest-day"></div></section>

<!-- 模块 9 -->
<section class="diet-section">
    <div class="diet-collapse" data-collapse>
        <div class="diet-collapse__head" data-toggle><h3>原片系数表（克 / 公斤体重 / 天）</h3><span>▾</span></div>
        <div class="diet-collapse__body">
            <p>以视频中的最终系数表为准：</p>
            <h4 style="color:var(--white);font-size:14px;margin-top:var(--space-3);">男性</h4>
            <table class="diet-table">
                <thead><tr><th>每周运动时长</th><th>碳水 (×kg)</th><th>蛋白质 (×kg)</th><th>脂肪 (×kg)</th></tr></thead>
                <tbody><tr><td>0-1 小时</td><td>1.6</td><td>1.2</td><td>0.7</td></tr><tr><td>2-3 小时</td><td>2.2</td><td>1.4</td><td>0.8</td></tr><tr><td>4-5 小时</td><td>2.6</td><td>1.6</td><td>0.9</td></tr><tr><td>6-8 小时</td><td>3.2</td><td>1.8</td><td>1.0</td></tr><tr><td>8 小时以上</td><td>3.6</td><td>2.0</td><td>1.0</td></tr></tbody>
            </table>
            <h4 style="color:var(--white);font-size:14px;margin-top:var(--space-3);">女性</h4>
            <table class="diet-table">
                <thead><tr><th>每周运动时长</th><th>碳水 (×kg)</th><th>蛋白质 (×kg)</th><th>脂肪 (×kg)</th></tr></thead>
                <tbody><tr><td>0-1 小时</td><td>1.4</td><td>1.0</td><td>0.6</td></tr><tr><td>2-3 小时</td><td>1.8</td><td>1.2</td><td>0.7</td></tr><tr><td>4-5 小时</td><td>2.2</td><td>1.4</td><td>0.8</td></tr><tr><td>6-8 小时</td><td>2.6</td><td>1.6</td><td>0.9</td></tr><tr><td>8 小时以上</td><td>3.0</td><td>1.8</td><td>0.9</td></tr></tbody>
            </table>
        </div>
    </div><div class="diet-video-slot" data-topic="holiday-cut"></div></section>
`;



// 加载 5 个饮食视频，填到 DIET_PRINCIPLE_HTML 内的 5 个插槽
async function loadAndFillDietVideos(principleRoot) {
    try {
        const r = await fetch(`${API}/tan-diet`);
        if (!r.ok) return;
        const d = await r.json();
        const topics = d.topics || [];
        const platIcon = { 'B站': '📺', '抖音': '🎵' };
        principleRoot.querySelectorAll('.diet-video-slot').forEach(slot => {
            const key = slot.dataset.topic;
            const t = topics.find(x => x.id === key);
            if (!t) return;
            const url = t.url || '#';
            slot.innerHTML = `
                <a class="diet-video-card" href="${url}" target="_blank" rel="noreferrer">
                    <div class="diet-video-card__icon">${platIcon[t.platform] || '🎬'}</div>
                    <div class="diet-video-card__main">
                        <div class="diet-video-card__title">📺 相关原片：${escapeHtml(t.title)}</div>
                        <div class="diet-video-card__meta">${escapeHtml(t.platform)} · ${t.related_count} 个相关动作</div>
                        <div class="diet-video-card__desc">${escapeHtml(t.description || '')}</div>
                        <span class="diet-video-card__watch">▶ 去 ${escapeHtml(t.platform)} 观看</span>
                    </div>
                </a>
            `;
        });
    } catch (e) {
        console.warn('[tan] load diet videos failed', e);
    }
}

function runDietCalc(root) {
    const g = root.querySelector('#gender')?.value;
    const w = parseFloat(root.querySelector('#weight')?.value) || 0;
    const a = parseFloat(root.querySelector('#age')?.value) || 0;
    const h = parseFloat(root.querySelector('#height')?.value) || 0;
    const hours = root.querySelector('#hours')?.value;
    const goal = root.querySelector('#goal')?.value;
    if (!g) { alert('请选择性别'); return; }
    if (!w || !a) { alert('请填写体重和年龄'); return; }
    if (!hours) { alert('请选择每周运动时长档位'); return; }
    const COEF = {
        male:   { '0-1':[1.6,1.2,0.7], '2-3':[2.2,1.4,0.8], '4-5':[2.6,1.6,0.9], '6-8':[3.2,1.8,1.0], '8+':[3.6,2.0,1.0] },
        female: { '0-1':[1.4,1.0,0.6], '2-3':[1.8,1.2,0.7], '4-5':[2.2,1.4,0.8], '6-8':[2.6,1.6,0.9], '8+':[3.0,1.8,0.9] },
    };
    const FOOD = {
        rice: { carb: 28.2, prot: 2.7, fat: 0.3 },
        breast: { prot: 33.4, fat: 2.7 },
        thigh: { prot: 28.7, fat: 8.0 },
        egg: { prot: 12.6, fat: 10.6, per: 50 },
    };
    const coef = COEF[g] && COEF[g][hours] ? COEF[g][hours] : COEF[g]?.['2-3'];
    if (!coef) { alert('数据异常'); return; }
    const [kC, kP, kF] = coef;
    const carbG = w * kC, protG = w * kP, fatG = w * kF;
    const kcalC = carbG * 4, kcalP = protG * 4, kcalF = fatG * 9;
    const total = kcalC + kcalP + kcalF;

    root.querySelector('#resultParams').textContent = '输入参数 · ' + (g === 'male' ? '男' : '女') + ' · ' + w + ' kg · 每周' + hours + '小时';
    root.querySelector('#carbG').textContent = Math.round(carbG);
    root.querySelector('#protG').textContent = Math.round(protG);
    root.querySelector('#fatG').textContent = Math.round(fatG);
    root.querySelector('#carbF').textContent = '体重 × ' + kC;
    root.querySelector('#protF').textContent = '体重 × ' + kP;
    root.querySelector('#fatF').textContent  = '体重 × ' + kF;
    root.querySelector('#totalKcal').textContent = Math.round(total);

    const pCarb = total ? kcalC / total * 100 : 0;
    const pProt = total ? kcalP / total * 100 : 0;
    const pFat  = total ? kcalF / total * 100 : 0;
    const barC = root.querySelector('#barCarb');
    const barP = root.querySelector('#barProt');
    const barF = root.querySelector('#barFat');
    if (barC) { barC.style.width = pCarb + '%'; barC.textContent = '碳水 ' + pCarb.toFixed(0) + '%'; }
    if (barP) { barP.style.width = pProt + '%'; barP.textContent = '蛋白 ' + pProt.toFixed(0) + '%'; }
    if (barF) { barF.style.width = pFat  + '%'; barF.textContent = '脂肪 ' + pFat.toFixed(0) + '%'; }

    root.querySelector('#carbG2').textContent = Math.round(carbG);
    root.querySelector('#riceG').textContent = Math.round(carbG / FOOD.rice.carb * 100);

    const protT = protG;
    root.querySelector('#protRow1T').textContent = Math.round(protT);
    root.querySelector('#protRow1G').textContent = Math.round(protT / FOOD.breast.prot * 100);
    root.querySelector('#protRow2T').textContent = Math.round(protT);
    root.querySelector('#protRow2G').textContent = Math.round(protT / FOOD.thigh.prot * 100);
    root.querySelector('#protRow3T').textContent = Math.round(protT);
    root.querySelector('#protRow3G').textContent = Math.round(protT / FOOD.egg.prot / (FOOD.egg.per / 100));

    const eggN = parseInt(root.querySelector('#eggCount')?.value) || 0;
    const meat = root.querySelector('#meatToggle button[aria-pressed="true"]')?.dataset.meat || 'breast';
    const meatFood = meat === 'thigh' ? FOOD.thigh : FOOD.breast;
    const eggProt = eggN * FOOD.egg.per / 100 * FOOD.egg.prot;
    const riceNeed = Math.round(carbG / FOOD.rice.carb * 100);
    const remainingProt = Math.max(0, protG - eggProt);
    const meatNeed = Math.round(remainingProt / meatFood.prot * 100);
    root.querySelector('#outRice').textContent = riceNeed;
    root.querySelector('#outMeat').textContent = meatNeed;
    root.querySelector('#outMeatLabel').textContent = meat === 'breast' ? '鸡胸肉熟重' : '鸡腿肉熟重';
    root.querySelector('#outEgg').textContent = eggN;

    const riceFat = riceNeed / 100 * FOOD.rice.fat;
    const meatFat = meatNeed / 100 * meatFood.fat;
    const eggFat  = eggN * FOOD.egg.per / 100 * FOOD.egg.fat;
    const comboFat = riceFat + meatFat + eggFat;
    const fatRemain = Math.max(0, fatG - comboFat);
    root.querySelector('#fatNote').innerHTML = '这个组合自带约 <b>' + comboFat.toFixed(1) + 'g</b> 脂肪。相对全天 <b>' + Math.round(fatG) + 'g</b> 参考，尚余约 <b>' + fatRemain.toFixed(1) + 'g</b>，由其他食物和烹调用油共享。';

    if (h) {
        const rmr = Math.round(10 * w + 6.25 * h - 5 * a + (g === 'male' ? 5 : -161));
        const rmrEl = root.querySelector('#rmrKcal');
        if (rmrEl) rmrEl.textContent = rmr;
        const warn = root.querySelector('#dietWarn');
        if (warn) warn.style.display = (rmr && total < rmr) ? 'block' : 'none';
    }

    const resultSection = root.querySelector('#resultSection');
    if (resultSection) {
        resultSection.classList.add('is-shown');
        resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

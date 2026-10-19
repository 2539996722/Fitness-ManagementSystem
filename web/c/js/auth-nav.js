// auth-nav.js — 顶部导航登录/登出按钮显隐
//
// 用法：在 HTML 顶部导航区域放三个元素：
//   <a class="btn btn--ghost" id="navLogin" href="/c/login.html">登录</a>
//   <a class="btn btn--primary" id="navRegister" href="/c/register.html">注册</a>
//   <button class="btn btn--ghost" id="navLogout" style="display:none">退出</button>
//
// 行为：
// - 读 localStorage.fitHubToken 判定是否已登录
// - 已登录：隐藏 登录/注册，显示 退出；点击退出清 token + 跳登录页
// - 未登录：显示 登录/注册，隐藏 退出

(function () {
    const navLogin = document.getElementById('navLogin');
    const navRegister = document.getElementById('navRegister');
    const navLogout = document.getElementById('navLogout');
    if (!navLogin || !navRegister || !navLogout) return;

    function readToken() {
        try { return localStorage.getItem('fitHubToken') || ''; } catch (e) { return ''; }
    }
    function clearToken() {
        try { localStorage.removeItem('fitHubToken'); } catch (e) {}
    }

    function show(isLoggedIn) {
        navLogin.style.display = isLoggedIn ? 'none' : '';
        navRegister.style.display = isLoggedIn ? 'none' : '';
        navLogout.style.display = isLoggedIn ? '' : 'none';
    }

    show(!!readToken());

    navLogout.addEventListener('click', (e) => {
        e.preventDefault();
        clearToken();
        show(false);
        location.href = '/c/login.html';
    });
})();

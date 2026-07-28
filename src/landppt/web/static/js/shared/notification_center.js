/**
 * LandPPT 通知中心（导航栏铃铛）
 *
 * 挂载为 window.NotificationCenter：
 *   NotificationCenter.mount({ bell: 'navNotificationBell', badge: 'navNotificationBadge' })
 *
 * 轮询未读数，展开时拉取最近通知；可选地在获得授权后同时弹出浏览器系统通知。
 */
(function () {
    'use strict';

    if (window.NotificationCenter) return;

    var POLL_INTERVAL_MS = 60000;
    var MAX_INTERVAL_MS = 300000;
    var DESKTOP_PREF_KEY = 'landppt.notifications.desktop';

    var LEVELS = { info: 1, success: 1, warning: 1, error: 1 };

    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function resolveElement(target) {
        if (!target) return null;
        return typeof target === 'string' ? document.getElementById(target) : target;
    }

    function formatTime(epochSeconds) {
        var value = Number(epochSeconds);
        if (!value) return '';
        var date = new Date(value * 1000);
        var diff = Date.now() - date.getTime();
        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前';
        if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前';
        return date.toLocaleString('zh-CN', { hour12: false });
    }

    function desktopEnabled() {
        try {
            return window.localStorage.getItem(DESKTOP_PREF_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function setDesktopEnabled(enabled) {
        try {
            window.localStorage.setItem(DESKTOP_PREF_KEY, enabled ? '1' : '0');
        } catch (e) { /* 隐私模式下忽略 */ }
    }

    function Center(options) {
        this.bell = resolveElement(options.bell);
        this.badge = resolveElement(options.badge);
        this.panel = null;
        this.open = false;
        this.interval = POLL_INTERVAL_MS;
        this.timer = null;
        this.unreadCount = 0;
        this.seenIds = {};
        this.primed = false;
    }

    Center.prototype.mount = function () {
        if (!this.bell) return;
        var self = this;

        this.panel = document.createElement('div');
        this.panel.className = 'ln-nc-panel';
        this.panel.hidden = true;
        this.panel.setAttribute('role', 'dialog');
        this.panel.setAttribute('aria-label', '通知');
        document.body.appendChild(this.panel);

        this.bell.addEventListener('click', function (event) {
            event.preventDefault();
            self.toggle();
        });

        document.addEventListener('click', function (event) {
            if (!self.open) return;
            if (self.panel.contains(event.target) || self.bell.contains(event.target)) return;
            self.close();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && self.open) self.close();
        });

        window.addEventListener('resize', function () {
            if (self.open) self.position();
        });

        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) self.poll();
        });

        this.poll();
    };

    Center.prototype.schedule = function () {
        var self = this;
        clearTimeout(this.timer);
        this.timer = setTimeout(function () { self.poll(); }, this.interval);
    };

    Center.prototype.poll = function () {
        if (document.hidden) { this.schedule(); return; }
        var self = this;
        fetch('/api/notifications/unread-count', { headers: { 'Accept': 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                self.interval = POLL_INTERVAL_MS;
                var count = Number(data && data.unread_count) || 0;
                var grew = count > self.unreadCount;
                self.setUnread(count);
                if (self.open) self.load();
                else if (grew && self.primed) self.maybeDesktopNotify();
                self.primed = true;
                self.schedule();
            })
            .catch(function () {
                self.interval = Math.min(MAX_INTERVAL_MS, self.interval * 2);
                self.schedule();
            });
    };

    Center.prototype.setUnread = function (count) {
        this.unreadCount = count;
        if (!this.badge) return;
        this.badge.textContent = count > 99 ? '99+' : String(count);
        this.badge.hidden = count <= 0;
    };

    /** 未读增加时拉取最新一条，弹出浏览器系统通知（需用户已在面板中开启）。 */
    Center.prototype.maybeDesktopNotify = function () {
        if (!('Notification' in window)) return;
        if (!desktopEnabled() || Notification.permission !== 'granted') return;

        var self = this;
        fetch('/api/notifications?limit=1&unread_only=true', { headers: { 'Accept': 'application/json' } })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                var latest = data && data.notifications && data.notifications[0];
                if (!latest || self.seenIds[latest.id]) return;
                self.seenIds[latest.id] = true;
                var desktop = new Notification(latest.title, {
                    body: latest.body || '',
                    tag: latest.id,
                });
                desktop.onclick = function () {
                    window.focus();
                    if (latest.link_url) window.location.href = latest.link_url;
                    desktop.close();
                };
            })
            .catch(function () { /* 桌面通知失败不影响站内通知 */ });
    };

    Center.prototype.toggle = function () {
        if (this.open) this.close();
        else this.show();
    };

    Center.prototype.show = function () {
        this.open = true;
        this.panel.hidden = false;
        this.bell.setAttribute('aria-expanded', 'true');
        this.position();
        this.renderLoading();
        this.load();
    };

    Center.prototype.close = function () {
        this.open = false;
        this.panel.hidden = true;
        this.bell.setAttribute('aria-expanded', 'false');
    };

    Center.prototype.position = function () {
        var rect = this.bell.getBoundingClientRect();
        var width = this.panel.offsetWidth || 360;
        var gap = 8;
        var edge = 12;
        var left = Math.min(
            Math.max(edge, rect.right - width),
            Math.max(edge, window.innerWidth - width - edge)
        );
        this.panel.style.left = left + 'px';
        this.panel.style.top = Math.min(rect.bottom + gap, window.innerHeight - 80) + 'px';
    };

    Center.prototype.renderLoading = function () {
        this.panel.innerHTML = '<div class="ln-nc-empty"><i class="fas fa-spinner fa-spin"></i> 加载中…</div>';
    };

    Center.prototype.load = function () {
        var self = this;
        fetch('/api/notifications?limit=20', { headers: { 'Accept': 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                self.setUnread(Number(data && data.unread_count) || 0);
                self.render((data && data.notifications) || []);
            })
            .catch(function () {
                self.panel.innerHTML = '<div class="ln-nc-empty">通知加载失败，请稍后重试</div>';
            });
    };

    Center.prototype.render = function (notifications) {
        var self = this;
        var supportsDesktop = 'Notification' in window;
        var desktopOn = supportsDesktop && desktopEnabled() && Notification.permission === 'granted';

        var itemsHtml = notifications.length
            ? notifications.map(function (item) {
                var level = LEVELS[item.level] ? item.level : 'info';
                return '' +
                    '<li>' +
                    '<button type="button" class="ln-nc-item' + (item.is_read ? '' : ' is-unread') + '" ' +
                    'data-id="' + escapeHtml(item.id) + '" ' +
                    'data-link="' + escapeHtml(item.link_url || '') + '">' +
                    '<span class="ln-nc-item-top">' +
                    '<span class="ln-nc-dot ln-nc-dot--' + level + '"></span>' +
                    '<span class="ln-nc-item-title">' + escapeHtml(item.title) + '</span>' +
                    '</span>' +
                    (item.body ? '<span class="ln-nc-item-body">' + escapeHtml(item.body) + '</span>' : '') +
                    '<span class="ln-nc-item-time">' + escapeHtml(formatTime(item.created_at)) + '</span>' +
                    '</button>' +
                    '</li>';
            }).join('')
            : '';

        this.panel.innerHTML = '' +
            '<div class="ln-nc-head">' +
            '<h4 class="ln-nc-title">通知</h4>' +
            '<div class="ln-nc-head-actions">' +
            (this.unreadCount > 0
                ? '<button type="button" class="ln-nc-link" data-nc-action="read-all">全部已读</button>'
                : '') +
            '</div>' +
            '</div>' +
            (itemsHtml
                ? '<ul class="ln-nc-list">' + itemsHtml + '</ul>'
                : '<div class="ln-nc-empty">暂无通知</div>') +
            (supportsDesktop && !desktopOn
                ? '<div class="ln-nc-foot"><button type="button" class="ln-nc-link" data-nc-action="enable-desktop">' +
                  '开启浏览器桌面通知</button></div>'
                : '');

        this.panel.querySelectorAll('.ln-nc-item').forEach(function (button) {
            button.addEventListener('click', function () {
                self.handleItemClick(button.dataset.id, button.dataset.link, button);
            });
        });

        var readAll = this.panel.querySelector('[data-nc-action="read-all"]');
        if (readAll) readAll.addEventListener('click', function () { self.markAllRead(); });

        var enableDesktop = this.panel.querySelector('[data-nc-action="enable-desktop"]');
        if (enableDesktop) {
            enableDesktop.addEventListener('click', function () { self.enableDesktop(); });
        }

        this.position();
    };

    Center.prototype.handleItemClick = function (id, link, button) {
        var self = this;
        var wasUnread = button && button.classList.contains('is-unread');
        if (button) button.classList.remove('is-unread');

        var done = wasUnread
            ? fetch('/api/notifications/' + encodeURIComponent(id) + '/read', { method: 'POST' })
                .then(function (response) { return response.ok ? response.json() : null; })
                .then(function (data) {
                    if (data) self.setUnread(Number(data.unread_count) || 0);
                })
                .catch(function () { /* 标记失败时仍然允许跳转 */ })
            : Promise.resolve();

        done.then(function () {
            if (link) window.location.href = link;
        });
    };

    Center.prototype.markAllRead = function () {
        var self = this;
        fetch('/api/notifications/read-all', { method: 'POST' })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function () {
                self.setUnread(0);
                self.load();
            })
            .catch(function () {
                if (window.Notify) window.Notify.error('操作失败，请稍后重试');
            });
    };

    /** 权限请求必须由用户手势触发，否则浏览器会直接拒绝。 */
    Center.prototype.enableDesktop = function () {
        var self = this;
        if (!('Notification' in window)) return;
        Notification.requestPermission().then(function (permission) {
            if (permission === 'granted') {
                setDesktopEnabled(true);
                if (window.Notify) window.Notify.success('已开启桌面通知');
            } else {
                setDesktopEnabled(false);
                if (window.Notify) window.Notify.warning('浏览器已拒绝通知权限');
            }
            if (self.open) self.load();
        });
    };

    window.NotificationCenter = {
        mount: function (options) {
            var center = new Center(options || {});
            center.mount();
            return center;
        }
    };
})();

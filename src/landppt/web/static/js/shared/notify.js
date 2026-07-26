/**
 * LandPPT 共享通知组件
 *
 * 挂载为 window.Notify，零依赖，可在任意页面（含 ES module）中使用：
 *   Notify.success('已保存')                                  // toast
 *   Notify.error('保存失败：' + err.message)
 *   Notify.warning('配置未生效')
 *   Notify.info('正在后台处理')
 *   await Notify.confirm('确定删除该项目吗？', { danger: true }) // → boolean
 *   await Notify.prompt('新模板名称', { defaultValue: name })   // → string | null
 *   await Notify.alert('生成完成，即将跳转')                     // 模态提示，需用户确认
 *
 * 消息一律以纯文本渲染（textContent），换行符 \n 会保留为换行。
 */
(function () {
    'use strict';

    if (window.Notify) return;

    var ICONS = {
        success: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10" cy="10" r="8.25"/><path d="M6.5 10.5l2.3 2.3 4.7-5.1"/></svg>',
        error: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="10" r="8.25"/><path d="M7.2 7.2l5.6 5.6M12.8 7.2l-5.6 5.6"/></svg>',
        warning: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2.8L18.2 17H1.8L10 2.8z"/><path d="M10 8v4"/><path d="M10 14.6v.2"/></svg>',
        info: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="10" r="8.25"/><path d="M10 9v5"/><path d="M10 6v.2"/></svg>'
    };

    var toastRoot = null;
    var MAX_TOASTS = 5;

    function hoistToastRoot() {
        // popover 将容器提入 top layer。top layer 按打开顺序堆叠（z-index 无效），
        // 每次显示 toast 都重新 hoist，才能压过此后打开的 showModal 弹窗
        if (typeof toastRoot.showPopover !== 'function') return;
        try {
            if (!toastRoot.hasAttribute('popover')) toastRoot.setAttribute('popover', 'manual');
            if (toastRoot.matches(':popover-open')) toastRoot.hidePopover();
            toastRoot.showPopover();
        } catch (e) {
            toastRoot.removeAttribute('popover');
        }
    }

    function ensureToastRoot() {
        if (!toastRoot || !document.body.contains(toastRoot)) {
            toastRoot = document.createElement('div');
            toastRoot.className = 'ln-toast-root';
            toastRoot.setAttribute('aria-live', 'polite');
            document.body.appendChild(toastRoot);
        }
        hoistToastRoot();
        return toastRoot;
    }

    function removeToast(el) {
        if (el.dataset.lnRemoving) return;
        el.dataset.lnRemoving = '1';
        el.classList.remove('ln-in');
        el.classList.add('ln-out');
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 240);
    }

    /**
     * @param {string} message
     * @param {{type?: 'success'|'error'|'warning'|'info', duration?: number}} [opts]
     */
    function toast(message, opts) {
        opts = opts || {};
        var type = ICONS[opts.type] ? opts.type : 'info';
        var duration = typeof opts.duration === 'number' ? opts.duration
            : (type === 'error' ? 5000 : 3200);

        var root = ensureToastRoot();
        while (root.children.length >= MAX_TOASTS) {
            removeToast(root.children[0]);
            if (root.children[0] && root.children[0].dataset.lnRemoving) {
                root.removeChild(root.children[0]);
            }
        }

        var el = document.createElement('div');
        el.className = 'ln-toast ln-toast--' + type;
        if (type === 'error' || type === 'warning') el.setAttribute('role', 'alert');

        var icon = document.createElement('span');
        icon.className = 'ln-toast__icon';
        icon.innerHTML = ICONS[type];

        var msg = document.createElement('div');
        msg.className = 'ln-toast__msg';
        msg.textContent = String(message);

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'ln-toast__close';
        close.setAttribute('aria-label', '关闭通知');
        close.innerHTML = '<svg viewBox="0 0 14 14" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12"/></svg>';
        close.addEventListener('click', function () { removeToast(el); });

        el.appendChild(icon);
        el.appendChild(msg);
        el.appendChild(close);
        root.appendChild(el);

        requestAnimationFrame(function () { el.classList.add('ln-in'); });

        if (duration > 0) {
            var remaining = duration;
            var startedAt = Date.now();
            var timer = setTimeout(function () { removeToast(el); }, remaining);
            el.addEventListener('mouseenter', function () {
                clearTimeout(timer);
                remaining -= Date.now() - startedAt;
            });
            el.addEventListener('mouseleave', function () {
                startedAt = Date.now();
                timer = setTimeout(function () { removeToast(el); }, Math.max(600, remaining));
            });
        }
        return el;
    }

    /* ── 模态对话框（同一时刻只显示一个，其余排队） ───────── */
    var dialogQueue = Promise.resolve();
    var dialogSeq = 0;
    var savedPageFocus = null;

    function queueDialog(build) {
        var run = dialogQueue.then(function () {
            return new Promise(build);
        });
        // 队列自身吞掉结果，避免一次 reject 卡死后续对话框
        dialogQueue = run.then(function () { }, function () { });
        return run;
    }

    /**
     * @param {object} cfg
     *   title, message, input(bool), defaultValue, placeholder,
     *   confirmText, cancelText(null 则无取消键), danger(bool)
     * @param {(result: any) => void} done  confirm→boolean / prompt→string|null / alert→undefined
     */
    function openDialog(cfg, done) {
        var previouslyFocused = document.activeElement;
        // 排队的下一个对话框在上一个尚未移除时创建，此刻焦点还停在旧对话框的
        // 按钮上——把真正的页面焦点接力传下去，队列结束后才能还给页面
        if (previouslyFocused && previouslyFocused.closest
            && previouslyFocused.closest('.ln-dialog-overlay')) {
            previouslyFocused = savedPageFocus;
        } else {
            savedPageFocus = previouslyFocused;
        }

        // 优先用原生 <dialog>.showModal()：进入 top layer，可盖住页面自身的
        // showModal 弹窗，且弹窗期间页面内容自动 inert（不可点击/聚焦）
        var useNativeDialog = typeof HTMLDialogElement === 'function'
            && typeof HTMLDialogElement.prototype.showModal === 'function';
        var overlay = document.createElement(useNativeDialog ? 'dialog' : 'div');
        overlay.className = 'ln-dialog-overlay';

        var dialog = document.createElement('div');
        dialog.className = 'ln-dialog';
        dialog.setAttribute('role', cfg.cancelText === null ? 'alertdialog' : 'dialog');
        dialog.setAttribute('aria-modal', 'true');

        var titleEl = document.createElement('h3');
        titleEl.className = 'ln-dialog__title';
        titleEl.id = 'ln-dialog-title-' + (++dialogSeq);
        titleEl.textContent = cfg.title;
        dialog.setAttribute('aria-labelledby', titleEl.id);
        dialog.appendChild(titleEl);

        if (cfg.message) {
            var msgEl = document.createElement('p');
            msgEl.className = 'ln-dialog__msg';
            msgEl.textContent = String(cfg.message);
            dialog.appendChild(msgEl);
        }

        var inputEl = null;
        if (cfg.input) {
            inputEl = document.createElement('input');
            inputEl.type = 'text';
            inputEl.className = 'ln-dialog__input';
            inputEl.value = cfg.defaultValue || '';
            if (cfg.placeholder) inputEl.placeholder = cfg.placeholder;
            inputEl.setAttribute('aria-label', cfg.title);
            dialog.appendChild(inputEl);
        }

        var actions = document.createElement('div');
        actions.className = 'ln-dialog__actions';

        var cancelBtn = null;
        if (cfg.cancelText !== null) {
            cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'ln-dialog__btn';
            cancelBtn.textContent = cfg.cancelText;
            actions.appendChild(cancelBtn);
        }

        var okBtn = document.createElement('button');
        okBtn.type = 'button';
        okBtn.className = 'ln-dialog__btn ' +
            (cfg.danger ? 'ln-dialog__btn--danger' : 'ln-dialog__btn--primary');
        okBtn.textContent = cfg.confirmText;
        actions.appendChild(okBtn);

        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        var settled = false;
        function settle(result) {
            if (settled) return;
            settled = true;
            document.removeEventListener('keydown', onKeydown, true);
            if (useNativeDialog && overlay.open) {
                try { overlay.close(); } catch (e) { }
            }
            overlay.classList.remove('ln-in');
            setTimeout(function () {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                // 若队列中的下一个对话框已经打开，不能把焦点抢回页面（否则
                // 用户对着可见的新对话框按 Enter 会触发页面上的旧按钮）
                var anotherOpen = document.querySelector('.ln-dialog-overlay');
                if (!anotherOpen && previouslyFocused
                    && typeof previouslyFocused.focus === 'function'
                    && document.contains(previouslyFocused)) {
                    previouslyFocused.focus({ preventScroll: true });
                }
            }, 200);
            done(result);
        }

        function okResult() {
            return cfg.input ? inputEl.value : true;
        }

        function cancelResult() {
            return cfg.input ? null : false;
        }

        okBtn.addEventListener('click', function () { settle(okResult()); });
        if (cancelBtn) cancelBtn.addEventListener('click', function () { settle(cancelResult()); });
        overlay.addEventListener('mousedown', function (e) {
            // 无取消键的 alert 弹窗不允许点遮罩关闭，必须显式确认
            if (e.target === overlay && cfg.cancelText !== null) settle(cancelResult());
        });

        function onKeydown(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                settle(cfg.cancelText === null ? okResult() : cancelResult());
            } else if (e.key === 'Enter' && cfg.input && e.target === inputEl) {
                e.preventDefault();
                e.stopPropagation();
                settle(okResult());
            } else if (e.key === 'Tab') {
                e.stopPropagation();
                // 焦点圈定在对话框内
                var focusables = [inputEl, cancelBtn, okBtn].filter(Boolean);
                var idx = focusables.indexOf(document.activeElement);
                if (idx === -1) {
                    e.preventDefault();
                    focusables[0].focus();
                } else {
                    e.preventDefault();
                    var next = e.shiftKey
                        ? (idx - 1 + focusables.length) % focusables.length
                        : (idx + 1) % focusables.length;
                    focusables[next].focus();
                }
            } else {
                // 对话框打开期间，其余按键不再冒泡到页面（阻止 Delete、
                // Ctrl+A 等页面级快捷键在等待确认时重入；不影响输入框打字）
                e.stopPropagation();
            }
        }
        document.addEventListener('keydown', onKeydown, true);
        if (useNativeDialog) {
            overlay.addEventListener('cancel', function (e) {
                e.preventDefault();
                settle(cfg.cancelText === null ? okResult() : cancelResult());
            });
            // 浏览器可能绕过 cancel 直接强制关闭（如安卓返回手势的第二次
            // 关闭请求、外部代码调用 close()）——必须兜底 settle，否则
            // promise 永不落定，对话框队列被永久卡死
            overlay.addEventListener('close', function () {
                settle(cfg.cancelText === null ? okResult() : cancelResult());
            });
            try {
                overlay.showModal();
            } catch (e) {
                // showModal 失败则退化为非模态显示（open 属性使 CSS 生效）
                overlay.setAttribute('open', '');
            }
        }

        requestAnimationFrame(function () {
            overlay.classList.add('ln-in');
            if (inputEl) {
                inputEl.focus();
                inputEl.select();
            } else if (cfg.danger && cancelBtn) {
                cancelBtn.focus();
            } else {
                okBtn.focus();
            }
        });
    }

    /**
     * @returns {Promise<boolean>}
     */
    function confirmDialog(message, opts) {
        opts = opts || {};
        return queueDialog(function (resolve) {
            openDialog({
                title: opts.title || '确认操作',
                message: message,
                confirmText: opts.confirmText || '确定',
                cancelText: opts.cancelText || '取消',
                danger: !!opts.danger
            }, resolve);
        });
    }

    /**
     * @returns {Promise<string|null>} 取消时为 null（与原生 prompt 一致）
     */
    function promptDialog(message, opts) {
        opts = opts || {};
        return queueDialog(function (resolve) {
            openDialog({
                title: opts.title || '请输入',
                message: message,
                input: true,
                defaultValue: opts.defaultValue || '',
                placeholder: opts.placeholder || '',
                confirmText: opts.confirmText || '确定',
                cancelText: opts.cancelText || '取消'
            }, resolve);
        });
    }

    /**
     * 模态提示（替代需要用户确认后才能继续的 alert，例如提示后立即跳转）。
     * @returns {Promise<void>}
     */
    function alertDialog(message, opts) {
        opts = opts || {};
        return queueDialog(function (resolve) {
            openDialog({
                title: opts.title || '提示',
                message: message,
                confirmText: opts.confirmText || '知道了',
                cancelText: null
            }, function () { resolve(undefined); });
        });
    }

    window.Notify = {
        toast: toast,
        success: function (m, o) { return toast(m, Object.assign({}, o, { type: 'success' })); },
        error: function (m, o) { return toast(m, Object.assign({}, o, { type: 'error' })); },
        warning: function (m, o) { return toast(m, Object.assign({}, o, { type: 'warning' })); },
        info: function (m, o) { return toast(m, Object.assign({}, o, { type: 'info' })); },
        confirm: confirmDialog,
        prompt: promptDialog,
        alert: alertDialog
    };
})();

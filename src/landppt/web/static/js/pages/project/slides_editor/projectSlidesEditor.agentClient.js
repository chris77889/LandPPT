/**
 * Slide edit agent 的唯一 SSE 客户端。
 *
 * 之前侧栏、元素浮窗、旧的 aiApply 各自写了一份流解析，事件名和错误处理都不一致。
 * 这里统一成一处：解析、分发、优雅停止、实时预览会话都在这个文件里。
 */
(function () {
    'use strict';

    const STREAM_URL = '/api/ai/slide-edit-agent/stream';
    const CANCEL_URL = '/api/ai/slide-edit-agent/cancel';

    /** 发出取消后等服务端自己收尾的时间；超时才硬断开。 */
    const GRACEFUL_CANCEL_TIMEOUT_MS = 15000;

    const EVENT_HANDLER_NAMES = {
        run_started: 'onRunStarted',
        protocol_changed: 'onProtocolChanged',
        turn_started: 'onTurnStarted',
        thinking: 'onThinking',
        tool_started: 'onToolStarted',
        tool_finished: 'onToolFinished',
        draft_updated: 'onDraft',
        validation: 'onValidation',
        run_finished: 'onFinished',
        error: 'onError'
    };

    function newRunId() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return `run-${window.crypto.randomUUID().replace(/-/g, '')}`;
        }
        return `run-${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`;
    }

    function callHandler(handlers, name, event) {
        const handler = handlers && handlers[name];
        if (typeof handler !== 'function') return;
        try {
            handler(event);
        } catch (error) {
            console.error(`[agentClient] handler ${name} threw`, error);
        }
    }

    /**
     * 一次 agent run。
     *
     * - `done` 是 Promise，resolve 出 { status, summary, proposal, iterationsUsed }
     * - `cancel()` 优雅停止：通知服务端后等它把停止前的草稿作为结果发回来
     * - `abort()` 直接断流，拿不到结果
     */
    class AgentRun {
        constructor({ payload, handlers = {} }) {
            this.runId = (payload && payload.runId) || newRunId();
            this.payload = Object.assign({}, payload, { runId: this.runId });
            this.handlers = handlers;
            this.controller = new AbortController();
            this.status = 'pending';
            this.result = null;
            this.lastError = '';
            this.cancelRequested = false;
            this._cancelTimer = null;
            this.done = this._start();
        }

        async _start() {
            let response;
            try {
                response = await fetch(STREAM_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.payload),
                    signal: this.controller.signal
                });
            } catch (error) {
                this.status = 'failed';
                throw normalizeError(error, '无法连接到 AI 服务');
            }

            if (!response.ok) {
                this.status = 'failed';
                const detail = await response.text().catch(() => '');
                throw new Error(detail || `请求失败：HTTP ${response.status}`);
            }
            if (!response.body || typeof response.body.getReader !== 'function') {
                this.status = 'failed';
                throw new Error('Agent 未返回可读取的流式响应');
            }

            try {
                await this._consume(response.body.getReader());
            } catch (error) {
                this.status = 'failed';
                throw normalizeError(error, '处理 Agent 流式响应时出错');
            } finally {
                this._clearCancelTimer();
            }

            if (!this.result) {
                this.status = 'failed';
                throw new Error(this.lastError || 'Agent 未返回结果');
            }
            return this.result;
        }

        async _consume(reader) {
            const decoder = new TextDecoder();
            let buffer = '';

            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    this._processLine(line);
                }
            }

            buffer += decoder.decode();
            if (buffer.trim()) {
                this._processLine(buffer);
            }
        }

        _processLine(line) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) return;

            const raw = trimmed.slice(5).trim();
            if (!raw) return;

            let event;
            try {
                event = JSON.parse(raw);
            } catch (error) {
                return;
            }
            if (!event || !event.type) return;
            // 服务端有可能同时在跑上一次 run（用户连点），只认自己这条流。
            if (event.runId && event.runId !== this.runId) return;

            this._dispatch(event);
        }

        _dispatch(event) {
            if (event.type === 'error') {
                this.lastError = event.message || event.error || this.lastError;
            }
            if (event.type === 'run_finished') {
                this.status = event.status || 'completed';
                this.result = {
                    runId: this.runId,
                    status: this.status,
                    summary: event.summary || '',
                    proposal: event.proposal || null,
                    iterationsUsed: event.iterationsUsed || 0,
                    error: event.error || ''
                };
            }

            callHandler(this.handlers, 'onEvent', event);
            const named = EVENT_HANDLER_NAMES[event.type];
            if (named) callHandler(this.handlers, named, event);
        }

        /** 优雅停止：服务端会把停止前的草稿作为 run_finished 发回来。 */
        async cancel() {
            if (this.cancelRequested || this.result) return;
            this.cancelRequested = true;

            try {
                await fetch(CANCEL_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ runId: this.runId })
                });
            } catch (error) {
                // 取消请求本身失败也没关系，下面的超时会硬断开。
            }

            this._clearCancelTimer();
            this._cancelTimer = setTimeout(() => this.abort(), GRACEFUL_CANCEL_TIMEOUT_MS);
        }

        abort() {
            this._clearCancelTimer();
            if (!this.result) this.status = 'aborted';
            try {
                this.controller.abort();
            } catch (error) {
                // ignore
            }
        }

        _clearCancelTimer() {
            if (this._cancelTimer) {
                clearTimeout(this._cancelTimer);
                this._cancelTimer = null;
            }
        }
    }

    function normalizeError(error, fallbackMessage) {
        if (error && (error.name === 'AbortError' || error.name === 'CanceledError')) {
            const aborted = new Error('已中止');
            aborted.aborted = true;
            return aborted;
        }
        if (error instanceof Error) return error;
        return new Error((error && String(error)) || fallbackMessage);
    }

    /**
     * 实时预览会话：把 agent 的中间草稿推进 iframe，但不写进 slidesData、不落库。
     * 用户点「撤销」就还原到 run 开始前的 HTML。
     */
    function beginPreviewSession(slideIndex) {
        // slidesData 是顶层 let，会被 normalizeSlidesDataToOutline 整体替换，
        // 所以读词法绑定而不是快照。
        const slides = typeof slidesData !== 'undefined' ? slidesData : window.slidesData;
        const baselineHtml = (slides && slides[slideIndex] ? slides[slideIndex].html_content : null) || '';
        let latestHtml = null;
        let released = false;

        function targetFrame() {
            if (released) return null;
            // 用户切页后就不再往画布上推草稿了。
            if (typeof currentSlideIndex === 'number' && currentSlideIndex !== slideIndex) return null;
            return document.getElementById('slideFrame');
        }

        return {
            slideIndex,
            baselineHtml,
            get latestHtml() {
                return latestHtml;
            },
            get dirty() {
                return latestHtml !== null && latestHtml !== baselineHtml;
            },
            push(html) {
                if (!html || released) return false;
                latestHtml = html;
                const frame = targetFrame();
                if (!frame || typeof setSafeIframeContent !== 'function') return false;
                setSafeIframeContent(frame, html);
                return true;
            },
            revert() {
                latestHtml = null;
                const frame = targetFrame();
                if (!frame || !baselineHtml || typeof setSafeIframeContent !== 'function') return false;
                setSafeIframeContent(frame, baselineHtml);
                return true;
            },
            release() {
                released = true;
            }
        };
    }

    window.landpptAgentClient = {
        start(options) {
            return new AgentRun(options || {});
        },
        beginPreviewSession,
        newRunId,
        STREAM_URL,
        CANCEL_URL
    };
})();

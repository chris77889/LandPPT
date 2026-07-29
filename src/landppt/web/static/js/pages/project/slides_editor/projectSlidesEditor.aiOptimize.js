        function getTargetAudience(outline) {
            if (!outline || !outline.metadata) {
                return '普通大众';
            }
            const audienceType = outline.metadata.target_audience;
            // 如果选择的是"自定义"，则使用custom_audience字段的值
            if (audienceType === '自定义' && outline.metadata.custom_audience) {
                return outline.metadata.custom_audience;
            }
            return audienceType || '普通大众';
        }

        // 创建美化的AI优化需求输入弹窗
        function showAIOptimizeModal(config) {
            return new Promise((resolve) => {
                // 创建模态框遮罩
                const modal = document.createElement('div');
                modal.className = 'ai-optimize-modal';
                modal.setAttribute('role', 'dialog');
                modal.setAttribute('aria-modal', 'true');
                modal.setAttribute('aria-label', String(config.title || 'AI优化'));

                // 创建弹窗内容
                const content = document.createElement('div');
                content.className = 'ai-optimize-modal__card';

                // 建议示例
                const suggestions = config.suggestions || [
                    '增加更多文字说明',
                    '简化内容，突出核心要点',
                    '添加数据支撑和案例分析',
                    '优化逻辑结构，增强说服力',
                    '增加视觉化描述建议'
                ];

                content.innerHTML = `
                    <div class="ai-optimize-modal__header">
                        <div class="ai-optimize-modal__header-content">
                            <div>
                                <h3 class="ai-optimize-modal__title">
                                    <i class="fas fa-magic"></i><span class="ai-optimize-title"></span>
                                </h3>
                                <p class="ai-optimize-modal__subtitle"></p>
                            </div>
                            <button type="button" class="ai-optimize-modal__close" aria-label="关闭">
                                <span aria-hidden="true">×</span>
                            </button>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__body">
                        <div class="current-info">
                            <div>
                                <strong><i class="fas fa-info-circle"></i> 当前内容</strong><br>
                                <span class="ai-optimize-current-info" style="white-space: pre-line;"></span>
                            </div>
                        </div>

                        <div class="input-group">
                            <label class="input-label">
                                <i class="fas fa-edit"></i> 请描述您的优化需求
                            </label>
                            <textarea class="input-textarea ai-optimize-input" aria-label="优化需求" placeholder="详细描述您希望如何优化此内容...

例如：
- 增加更多技术细节
- 重新组织逻辑结构
- 添加案例分析"></textarea>
                        </div>

                        <div class="suggestions">
                            <label class="suggestion-label">
                                <i class="fas fa-lightbulb"></i> 点击快捷建议快速填充
                            </label>
                            <div class="suggestion-list"></div>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__footer">
                        <div class="footer-hint">
                            <i class="fas fa-robot"></i> AI将根据您的需求智能优化内容
                        </div>
                        <div class="footer-actions">
                            <button type="button" class="outline-modal-btn ai-optimize-cancel">
                                <i class="fas fa-times"></i><span>取消</span>
                            </button>
                            <button type="button" class="outline-modal-btn outline-modal-btn--solid ai-optimize-confirm">
                                <i class="fas fa-magic"></i><span>开始优化</span>
                            </button>
                        </div>
                    </div>
                `;

                const previousFocus = document.activeElement;
                const input = content.querySelector('.ai-optimize-input');
                const confirmBtn = content.querySelector('.ai-optimize-confirm');
                const currentInfoElement = content.querySelector('.ai-optimize-current-info');
                content.querySelector('.ai-optimize-title').textContent = String(config.title || '');
                content.querySelector('.ai-optimize-modal__subtitle').textContent = String(config.subtitle || '');
                currentInfoElement.textContent = String(config.currentInfo || '');

                const suggestionList = content.querySelector('.suggestion-list');
                suggestions.forEach((suggestion) => {
                    const suggestionButton = document.createElement('button');
                    suggestionButton.type = 'button';
                    suggestionButton.className = 'suggestion-tag';
                    suggestionButton.textContent = String(suggestion);
                    suggestionButton.addEventListener('click', () => {
                        input.value = String(suggestion);
                        input.focus();
                    });
                    suggestionList.appendChild(suggestionButton);
                });

                let closed = false;
                function closeModal(value = null) {
                    if (closed) return;
                    closed = true;
                    document.removeEventListener('keydown', handleKeydown);
                    modal.remove();
                    previousFocus?.focus?.();
                    resolve(value);
                }

                function handleKeydown(event) {
                    if (event.key === 'Escape') {
                        event.preventDefault();
                        closeModal();
                        return;
                    }
                    if (event.key !== 'Tab') return;
                    const focusable = content.querySelectorAll('button:not([disabled]), textarea:not([disabled])');
                    const first = focusable[0];
                    const last = focusable[focusable.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                        event.preventDefault();
                        last.focus();
                    } else if (!event.shiftKey && document.activeElement === last) {
                        event.preventDefault();
                        first.focus();
                    }
                }

                content.querySelector('.ai-optimize-modal__close').addEventListener('click', () => closeModal());
                content.querySelector('.ai-optimize-cancel').addEventListener('click', () => closeModal());
                modal.addEventListener('click', (event) => {
                    if (event.target === modal) closeModal();
                });
                confirmBtn.addEventListener('click', () => {
                    const value = input.value.trim();
                    if (!value) {
                        input.classList.add('shake');
                        setTimeout(() => input.classList.remove('shake'), 500);
                        return;
                    }
                    closeModal(value);
                });

                modal.appendChild(content);
                document.body.appendChild(modal);
                document.addEventListener('keydown', handleKeydown);
                requestAnimationFrame(() => input.focus());
            });
        }

        // AI优化单页幻灯片大纲
        async function aiOptimizeSingleSlideInSlidesEditor() {
            // 从表单中获取当前数据
            const title = document.getElementById('slideTitle')?.value.trim() || '';
            const slideType = document.getElementById('slideType')?.value || 'content';
            const description = document.getElementById('slideDescription')?.value.trim() || '';

            // 获取所有内容要点
            let contentPoints = [];
            const bulletPointsContainer = document.getElementById('bulletPointsContainer');
            if (bulletPointsContainer) {
                const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
                contentPoints = Array.from(bulletPointItems).map(item => {
                    const textElement = item.querySelector('.bullet-point-text');
                    return textElement ? textElement.textContent.trim() : '';
                }).filter(point => point);
            }

            if (!title) {
                showNotification('请先输入页面标题', 'warning');
                return;
            }

            // 显示美化的优化需求输入弹窗
            let userRequest;
            try {
                userRequest = await showAIOptimizeModal({
                    title: `AI优化 - 第${currentSlideIndex + 1}页`,
                    subtitle: '让AI帮助您优化这一页的内容',
                    currentInfo: `标题：${title}\n类型：${slideType}\n内容要点：${contentPoints.length}个`,
                    suggestions: [
                        '增加更多技术细节和实例',
                        '简化内容，突出核心要点',
                        '优化逻辑结构，使内容更连贯',
                        '增强说服力，添加数据支撑',
                        '丰富表达方式，提升专业度'
                    ]
                });
            } catch (e) {
                return; // 用户取消
            }

            if (!userRequest || !userRequest.trim()) {
                return;
            }

            // 显示加载提示
            showNotification('AI正在优化第' + (currentSlideIndex + 1) + '页...', 'info');

            try {
                // 使用项目大纲数据
                if (!projectOutline || !projectOutline.slides) {
                    throw new Error('大纲数据不存在');
                }

                const outlineContent = JSON.stringify(projectOutline);

                // 调用AI优化接口
                const response = await fetch('/api/ai/optimize-outline', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        outline_content: outlineContent,
                        user_request: userRequest.trim(),
                        language: projectOutline?.metadata?.language || 'zh',
                        project_info: {
                            topic: projectOutline.title || '未知',
                            scenario: projectOutline.metadata?.scenario || '通用',
                            target_audience: getTargetAudience(projectOutline)
                        },
                        optimization_type: 'single',
                        slide_index: currentSlideIndex
                    })
                });

                const result = await response.json();

                if (result.success && result.optimized_content) {
                    // 解析优化后的单页数据
                    const optimizedSlide = JSON.parse(result.optimized_content);

                    // 更新弹窗中的表单
                    document.getElementById('slideTitle').value = optimizedSlide.title || '';
                    document.getElementById('slideType').value = optimizedSlide.slide_type || 'content';
                    document.getElementById('slideDescription').value = optimizedSlide.description || '';

                    // 更新内容要点
                    const container = document.getElementById('bulletPointsContainer');
                    if (container && optimizedSlide.content_points && optimizedSlide.content_points.length > 0) {
                        // 清空现有内容
                        container.innerHTML = '';

                        // 添加优化后的要点
                        optimizedSlide.content_points.forEach((point, index) => {
                            const pointDiv = document.createElement('div');
                            pointDiv.className = 'bullet-point-item';
                            pointDiv.setAttribute('data-index', index);
                            pointDiv.style.cssText = 'display: flex; align-items: flex-start; margin-bottom: 8px; padding: 8px; border-radius: 4px; transition: all 0.2s ease; position: relative;';
                            pointDiv.innerHTML = `
                                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                <div style="flex: 1; position: relative;">
                                    <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                </div>
                            `;
                            container.appendChild(pointDiv);
                        });
                    }

                    showNotification('✅ AI优化完成，请检查后保存', 'success');

                } else {
                    // 显示详细的错误信息
                    let errorMsg = result.error || '未知错误';
                    if (result.extracted_json) {
                        console.error('提取的JSON:', result.extracted_json);
                    }
                    if (result.raw_response) {
                        console.error('AI原始响应:', result.raw_response);
                    }
                    showNotification('AI优化失败: ' + errorMsg, 'error');
                }

            } catch (error) {
                console.error('AI优化失败:', error);
                showNotification('AI优化失败: ' + error.message, 'error');
            }
        }


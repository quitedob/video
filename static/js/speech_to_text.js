// 文件: static/js/speech_to_text.js
// 简短说明：负责语音转文字的HTTP请求处理和UI更新（带中文注释）

// ----- 配置与状态 -----
// 当前任务ID（客户端生成）
let currentTaskId = null;
// 处理状态
let isProcessing = false;
// 累积文本
let accumulatedText = '';
// 最近的块（用于重连支持）
let recentChunks = [];
const RECENT_LIMIT = 10;

// ----- DOM 元素快捷引用 -----
let startBtn, stopBtn, mediaFile, liveContainer, resultText, copyBtn, clearBtn, progressFill, statusMsg, taskInfo, downloadLink, consoleEl;

// 等待DOM加载完成后再初始化
document.addEventListener('DOMContentLoaded', () => {
  console.log('[前端] DOM加载完成，开始初始化应用...');

  // 初始化DOM元素引用
  console.log('[前端] 初始化DOM元素引用...');
  startBtn = document.getElementById('startBtn');
  stopBtn = document.getElementById('stopBtn');
  mediaFile = document.getElementById('mediaFile');
  liveContainer = document.getElementById('liveContainer');
  resultText = document.getElementById('resultText');
  copyBtn = document.getElementById('copyBtn');
  clearBtn = document.getElementById('clearBtn');
  progressFill = document.getElementById('progressFill');
  statusMsg = document.getElementById('statusMsg');
  taskInfo = document.getElementById('taskInfo');
  downloadLink = document.getElementById('downloadLink');
  consoleEl = document.getElementById('console');

  console.log('[前端] DOM元素检查结果:', {
    startBtn: !!startBtn,
    stopBtn: !!stopBtn,
    mediaFile: !!mediaFile,
    liveContainer: !!liveContainer,
    resultText: !!resultText,
    copyBtn: !!copyBtn,
    clearBtn: !!clearBtn,
    progressFill: !!progressFill,
    statusMsg: !!statusMsg,
    taskInfo: !!taskInfo,
    downloadLink: !!downloadLink,
    consoleEl: !!consoleEl
  });

  // 检查必要的DOM元素是否存在
  if (!startBtn || !stopBtn || !mediaFile) {
    console.error('[前端] 必要的DOM元素未找到，停止初始化');
    return;
  }

  console.log('[前端] DOM元素初始化完成，开始绑定事件监听器...');
  // 绑定事件监听器
  bindEvents();

  console.log('[前端] 事件监听器绑定完成，开始检查系统状态...');
  // 检查系统状态
  checkSystemStatus();

  console.log('[前端] 应用初始化完成');
});

// ----- 初始化完成 -----
console.log('[前端] 初始化完成，移除Socket.IO依赖');


// 常用日志函数
function logConsole(msg) {
  consoleEl.textContent = `控制台: ${msg}`;
}

// 自动滚动 live 区
function appendLive(text, isFinal = false) {
  console.log('[前端-显示] appendLive调用:', {
    text_length: text?.length || 0,
    text_preview: text?.substring(0, 50) + (text?.length > 50 ? '...' : ''),
    isFinal: isFinal,
    liveContainer_children_before: liveContainer.children.length
  });

  // 清理ASR标记
  const cleanText = cleanAsrText(text);
  console.log('[前端-显示] appendLive文本清理结果:', {
    raw_length: text.length,
    clean_length: cleanText.length,
    cleaned_chars: text.length - cleanText.length
  });

  const node = document.createElement('div');
  node.className = isFinal ? 'chunk final' : 'chunk';
  node.textContent = cleanText;

  console.log('[前端-显示] 创建chunk元素:', {
    className: node.className,
    textContent_length: node.textContent.length
  });

  liveContainer.appendChild(node);
  console.log('[前端-显示] chunk已添加到liveContainer，当前子元素数量:', liveContainer.children.length);

  liveContainer.scrollTop = liveContainer.scrollHeight;
  console.log('[前端-显示] 已滚动到底部，appendLive完成');
}

// 更新汇总显示
function appendToResult(text) {
  console.log('[前端-显示] appendToResult调用:', {
    text_length: text?.length || 0,
    text_preview: text?.substring(0, 50) + (text?.length > 50 ? '...' : ''),
    accumulatedText_before_length: accumulatedText.length
  });

  // 清理ASR标记
  const cleanText = cleanAsrText(text);
  console.log('[前端-显示] appendToResult文本清理结果:', {
    raw_length: text.length,
    clean_length: cleanText.length,
    cleaned_chars: text.length - cleanText.length
  });

  accumulatedText += (accumulatedText ? '\n' : '') + cleanText;
  resultText.textContent = accumulatedText;

  console.log('[前端-显示] appendToResult完成，累积文本总长度:', accumulatedText.length);
}

// 用于把后端 chunk 缓存到 recentChunks（重连支持）
function pushRecent(chunk) {
  recentChunks.push(chunk);
  while (recentChunks.length > RECENT_LIMIT) recentChunks.shift();
}

// 清理ASR文本标记
function cleanAsrText(text) {
  if (!text) return '';

  // 移除各种ASR标记
  let cleanedText = text
    // 移除语言标记
    .replace(/<\|zh\|>/g, '')
    .replace(/<\|en\|>/g, '')
    .replace(/<\|ja\|>/g, '')
    .replace(/<\|ko\|>/g, '')
    // 移除语气标记
    .replace(/<\|NEUTRAL\|>/g, '')
    .replace(/<\|HAPPY\|>/g, '')
    .replace(/<\|SAD\|>/g, '')
    .replace(/<\|ANGRY\|>/g, '')
    // 移除情绪标记
    .replace(/<\|EMO_UNKNOWN\|>/g, '')
    // 移除语音标记
    .replace(/<\|Speech\|>/g, '')
    // 移除内部文本规范化标记
    .replace(/<\|withitn\|>/g, '')
    // 移除其他可能的标记
    .replace(/<\|[^>]*\|>/g, '')
    // 清理多余的空格和换行
    .replace(/\s+/g, ' ')
    .trim();

  // 如果启用了过滤模式，移除指定的语气词
  const filterMode = document.getElementById('filterMode');
  if (filterMode && filterMode.checked) {
    // 定义要过滤的语气词列表
    const fillerWords = ['嗯', '行', '拜拜', '呃', '哎'];

    // 移除这些语气词（包括单独出现和带标点的情况）
    fillerWords.forEach(word => {
      // 移除单独的词
      const regex1 = new RegExp(`\\b${word}\\b`, 'g');
      cleanedText = cleanedText.replace(regex1, '');

      // 移除带标点的词
      const regex2 = new RegExp(`${word}[，。、！？,\\.!?\\s]+`, 'g');
      cleanedText = cleanedText.replace(regex2, '');

      // 移除开头的词
      const regex3 = new RegExp(`^${word}[，。、！？,\\.!?\\s]*`, 'g');
      cleanedText = cleanedText.replace(regex3, '');
    });

    // 清理多余的空格和标点
    cleanedText = cleanedText
      .replace(/\s+/g, ' ')
      .replace(/[，。、]{2,}/g, '，')
      .trim();
  }

  return cleanedText;
}

// ----- 绑定事件监听器 -----
function bindEvents() {
  // 文件预览删除按钮
  const filePreviewDelete = document.getElementById('filePreviewDelete');
  if (filePreviewDelete) {
    filePreviewDelete.addEventListener('click', () => {
      console.log('[前端-文件] 删除按钮被点击');
      clearFilePreview();
    });
  }

  // 折叠面板事件监听器
  console.log('[前端-事件] 设置折叠面板事件监听器');
  const fileInfoToggle = document.getElementById('fileInfoToggle');
  const processingOptionsToggle = document.getElementById('processingOptionsToggle');

  if (fileInfoToggle) {
    fileInfoToggle.addEventListener('click', function () {
      console.log('[前端-事件] 文件信息面板切换');
      const panel = document.getElementById('fileInfoPanel');
      const icon = this.querySelector('.fa-chevron-down');

      if (panel) {
        panel.classList.toggle('active');
        console.log('[前端-事件] 文件信息面板状态:', panel.classList.contains('active') ? '展开' : '收起');
      }
      if (icon) {
        icon.classList.toggle('rotated');
      }
    });
  }

  if (processingOptionsToggle) {
    processingOptionsToggle.addEventListener('click', function () {
      console.log('[前端-事件] 处理选项面板切换');
      const panel = document.getElementById('processingOptionsPanel');
      const icon = this.querySelector('.fa-chevron-down');

      if (panel) {
        panel.classList.toggle('active');
        console.log('[前端-事件] 处理选项面板状态:', panel.classList.contains('active') ? '展开' : '收起');
      }
      if (icon) {
        icon.classList.toggle('rotated');
      }
    });
  }

  // 上传并开始语音转文字处理
  startBtn.addEventListener('click', async () => {
    console.log('[前端-按钮] 开始按钮被点击');

    // 检查是否正在处理
    if (isProcessing) {
      console.log('[前端-按钮] 正在处理中，跳过');
      return;
    }

    // 生成客户端任务ID
    currentTaskId = 'client-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    console.log('[前端-按钮] 生成客户端task_id:', currentTaskId);

    const file = selectedFile;
    if (!file) {
      console.log('[前端-按钮] 未选择文件，显示提示');
      alert('请先选择要处理的媒体文件');
      return;
    }

    console.log('[前端-按钮] 准备的文件信息:', {
      name: file.name,
      size: file.size,
      type: file.type
    });

    // 更新UI状态
    taskInfo.textContent = `任务ID: ${currentTaskId}`;
    statusMsg.textContent = '正在上传和处理文件...';
    progressFill.style.width = '10%';
    startBtn.disabled = true;
    isProcessing = true;

    // 构造表单
    const form = new FormData();
    form.append('media_file', file);
    form.append('device', 'auto');
    form.append('task_id', currentTaskId);

    console.log('[前端-按钮] 构造的表单数据:', {
      media_file: file.name,
      device: 'auto',
      task_id: currentTaskId
    });

    // 发起HTTP请求
    console.log('[前端-按钮] 开始发起API请求到 /api/speech-to-text');
    try {
      const resp = await fetch('https://127.0.0.1:443/api/speech-to-text', { method: 'POST', body: form });
      console.log('[前端-按钮] API响应状态:', resp.status, resp.statusText);

      const j = await resp.json();
      console.log('[前端-按钮] API响应数据:', j);

      if (!resp.ok) {
        console.error('[前端-按钮] API请求失败:', j);
        statusMsg.textContent = `处理失败: ${j.error || JSON.stringify(j)}`;
        startBtn.disabled = false;
        isProcessing = false;
        progressFill.style.width = '0%';
        return;
      }

      console.log('[前端-按钮] API请求成功，处理响应');

      // 更新任务ID（如果后端返回了不同的ID）
      if (j.task_id && j.task_id !== currentTaskId) {
        currentTaskId = j.task_id;
        taskInfo.textContent = `任务ID: ${currentTaskId}`;
      }

      // 处理返回的完整文本
      if (j.text) {
        console.log('[前端-按钮] 收到完整文本，长度:', j.text.length);

        // 清空之前的显示
        liveContainer.innerHTML = '';
        resultText.textContent = '';

        // 显示完整文本
        const cleanText = cleanAsrText(j.text);
        appendLive(cleanText, true);
        resultText.textContent = cleanText;

        // 更新进度条
        progressFill.style.width = '100%';
        statusMsg.textContent = '处理完成！';

        logConsole(`处理完成，文本长度: ${cleanText.length} 字符`);
      } else {
        statusMsg.textContent = '处理完成但未返回文本';
        console.warn('[前端-按钮] 响应中没有text字段');
      }

      // 重置状态
      startBtn.disabled = false;
      isProcessing = false;

      console.log('[前端-按钮] 处理完成');
    } catch (err) {
      console.error('[前端-按钮] API请求异常:', err);
      statusMsg.textContent = '处理错误：' + err.message;
      startBtn.disabled = false;
      isProcessing = false;
      progressFill.style.width = '0%';
    }
  });

  // 停止/取消任务
  stopBtn.addEventListener('click', async () => {
    console.log('[前端-按钮] 停止按钮被点击');

    if (!isProcessing) {
      console.log('[前端-按钮] 当前没有正在处理的请求');
      return;
    }

    // 注意：HTTP请求一旦发出就无法真正"停止"，这里只是重置UI状态
    console.log('[前端-按钮] 重置处理状态');
    statusMsg.textContent = '已取消';
    startBtn.disabled = false;
    isProcessing = false;
    progressFill.style.width = '0%';
    currentTaskId = null;
    taskInfo.textContent = '任务ID: 无';

    console.log('[前端-按钮] 停止操作完成');
  });

  // 复制按钮
  copyBtn.addEventListener('click', () => {
    console.log('[前端-按钮] 复制按钮被点击');
    const text = resultText.textContent;
    console.log('[前端-按钮] 要复制的文本长度:', text.length);
    navigator.clipboard.writeText(text).then(() => {
      console.log('[前端-按钮] 文本复制成功');
      alert('已复制到剪贴板');
    }).catch(e => {
      console.error('[前端-按钮] 复制失败:', e);
      alert('复制失败: ' + e);
    });
  });

  // 清空按钮
  clearBtn.addEventListener('click', () => {
    console.log('[前端-按钮] 清空按钮被点击');
    console.log('[前端-按钮] 清空前状态:', {
      accumulatedText_length: accumulatedText.length,
      resultText_length: resultText.textContent.length,
      liveContainer_children: liveContainer.children.length
    });

    accumulatedText = '';
    resultText.textContent = '';
    liveContainer.innerHTML = '';

    console.log('[前端-按钮] 清空操作完成');
  });

  // 下载链接（从后端获取最终结果）
  downloadLink.addEventListener('click', (e) => {
    if (!currentTaskId) {
      e.preventDefault();
      alert('没有可下载的结果');
    }
  });

  // 为实时转写区域添加复制全文按钮
  addCopyButtonToLiveSection();

  // 初始化聊天功能
  initChatFeature();
}

// ----- HTTP 请求处理 -----
console.log('[前端] HTTP请求处理模块已加载');

// Socket.IO 代码已注释掉，因为我们使用HTTP请求
/*
socket.on('connect_error', (error) => {
  console.error('[前端-Socket] Socket.IO连接错误:', error);
  logConsole('socket 连接错误: ' + error.message);
});

socket.on('reconnect', (attemptNumber) => {
  console.log('[前端-Socket] Socket.IO重连成功，重连次数:', attemptNumber);
});

// 进度事件（后端 emit 'progress'）
socket.on('progress', (data) => {
  console.log('[前端-事件] 收到 progress 事件:', data);
  if (!data || data.task_id !== currentTaskId) {
    console.log('[前端-事件] progress 事件被过滤:', {
      data_task_id: data?.task_id,
      currentTaskId: currentTaskId,
      匹配: data?.task_id === currentTaskId
    });
    return;
  }
  const p = data.progress || 0;
  progressFill.style.width = `${p}%`;
  statusMsg.textContent = data.message || `进度 ${p}%`;
  console.log('[前端-事件] progress 事件处理完成，进度:', p + '%');
});

// 中间转写块（流式）: asr_transcript_chunk
socket.on('asr_transcript_chunk', (data) => {
  console.log('[前端-事件] 收到 asr_transcript_chunk 事件:', {
    data: data,
    currentTaskId: currentTaskId,
    data_task_id: data?.task_id,
    data_text_length: data?.text?.length || 0,
    data_is_final: data?.is_final,
    timestamp: new Date().toISOString()
  });

  // 如果后端没有 task_id 字段（兼容），则接受并显示（调试阶段建议不要过早丢弃）
  if (!data) {
    console.log('[前端-事件] asr_transcript_chunk 数据为空，跳过');
    return;
  }

  // 若 data.task_id 存在并且不匹配当前任务，则记录并跳过（避免交叉任务污染）
  if (data.task_id && currentTaskId && data.task_id !== currentTaskId) {
    console.log('[前端-事件] 跳过转写块（task_id 不匹配）:', {
      data_task_id: data.task_id,
      currentTaskId: currentTaskId,
      匹配结果: false
    });
    return;
  }

  console.log('[前端-事件] asr_transcript_chunk 事件验证通过，开始处理文本');

  // 清理特殊标记（如 <|zh|>、<|withitn|> 等），但保留原始以便调试
  const rawText = data.text || '';
  const cleanText = typeof cleanAsrText === 'function' ? cleanAsrText(rawText) : rawText;

  console.log('[前端-事件] 文本处理结果:', {
    rawText: rawText.substring(0, 100) + (rawText.length > 100 ? '...' : ''),
    cleanText: cleanText.substring(0, 100) + (cleanText.length > 100 ? '...' : ''),
    清理了字符数: rawText.length - cleanText.length,
    is_final: !!data.is_final
  });

  // 1) 追加到实时显示区（不论 is_final）
  console.log('[前端-事件] 追加到实时显示区');
  appendLive(cleanText, !!data.is_final);

  // 2) 累积到总文本（用于"复制全部"或下载）
  console.log('[前端-事件] 累积到总文本，当前累积长度:', accumulatedText.length);
  accumulatedText = (accumulatedText ? accumulatedText + ' ' : '') + cleanText;
  resultText.textContent = accumulatedText; // 同步到结果框（可调整为只在 is_final 时写入）

  console.log('[前端-事件] 更新结果框，总文本长度:', accumulatedText.length);

  // 3) 如果是最终块，触发 pushResult（将其加入最终列表 / 保存历史）
  if (data.is_final) {
    console.log('[前端-事件] 这是最终块，执行最终处理');
    appendToResult(cleanText);
    // 记录最近若干块以便重连/回放
    pushRecent(cleanText);
  } else {
    console.log('[前端-事件] 这不是最终块，跳过最终处理');
  }

  console.log('[前端-事件] asr_transcript_chunk 事件处理完成');
});

// 后端一次性 final 全文（非流式接口会触发 speech_result）
socket.on('speech_result', (data) => {
  console.log('[前端-事件] 收到 speech_result 事件:', data);
  if (!data || data.task_id !== currentTaskId) {
    console.log('[前端-事件] speech_result 事件被过滤:', {
      data_task_id: data?.task_id,
      currentTaskId: currentTaskId,
      匹配: data?.task_id === currentTaskId
    });
    return;
  }
  console.log('[前端-事件] speech_result 事件验证通过，开始处理');
  appendLive(data.text, true);
  appendToResult(data.text);
  // 显示下载链接（使用后端 /api/streaming-speech-result/<task_id>）
  downloadLink.href = `https://127.0.0.1:443/api/streaming-speech-result/${currentTaskId}`;
  downloadLink.style.display = 'inline-block';
  statusMsg.textContent = '识别完成（收到最终结果）';
  progressFill.style.width = '100%';
  startBtn.disabled = false;
  stopBtn.disabled = true;
  console.log('[前端-事件] speech_result 事件处理完成');
});

// 后端错误
socket.on('speech_error', (data) => {
  console.log('[前端-事件] 收到 speech_error 事件:', data);
  if (!data || (data.task_id && data.task_id !== currentTaskId)) {
    console.log('[前端-事件] speech_error 事件被过滤:', {
      data_task_id: data?.task_id,
      currentTaskId: currentTaskId,
      匹配: data?.task_id === currentTaskId
    });
    return;
  }
  console.log('[前端-事件] speech_error 事件验证通过，显示错误信息');
  statusMsg.textContent = '识别出错: ' + (data.error || JSON.stringify(data));
  logConsole('收到错误: ' + (data.error || JSON.stringify(data)));
  startBtn.disabled = false;
  stopBtn.disabled = true;
});

// 流结束（asr_stream_end）
socket.on('asr_stream_end', (data) => {
  console.log('[前端-事件] 收到 asr_stream_end 事件:', data);
  if (!data || data.task_id !== currentTaskId) {
    console.log('[前端-事件] asr_stream_end 事件被过滤:', {
      data_task_id: data?.task_id,
      currentTaskId: currentTaskId,
      匹配: data?.task_id === currentTaskId
    });
    return;
  }
  console.log('[前端-事件] asr_stream_end 事件验证通过，处理流结束');
  statusMsg.textContent = '流式处理结束';
  startBtn.disabled = false;
  stopBtn.disabled = true;
});

// 任务已创建事件（当后端发来 asr_task_created）
socket.on('asr_task_created', (data) => {
  console.log('[前端-事件] 收到 asr_task_created 事件:', data);
  if (!data) {
    console.log('[前端-事件] asr_task_created 数据为空，跳过');
    return;
  }
  console.log('[前端-事件] asr_task_created 事件验证通过，显示通知');
  logConsole('任务创建通知: ' + (data.message || ''));
});

// 断线重连/断开
socket.on('disconnect', () => {
  logConsole('socket 已断开');
  statusMsg.textContent = 'socket 已断开';
});
*/

// ----- 辅助函数 -----
function checkSystemStatus() {
  console.log('[前端-系统] 开始检查系统状态');

  // 检查文件上传区域的拖拽功能
  const fileUploadArea = document.getElementById('fileUploadArea');
  console.log('[前端-系统] 文件上传区域元素:', !!fileUploadArea);

  if (fileUploadArea) {
    console.log('[前端-系统] 设置拖拽事件监听器');

    fileUploadArea.addEventListener('dragover', (e) => {
      console.log('[前端-系统] dragover事件触发');
      e.preventDefault();
      e.stopPropagation();
      fileUploadArea.style.borderColor = '#007bff';
      fileUploadArea.style.background = '#f0f8ff';
    });

    fileUploadArea.addEventListener('dragleave', (e) => {
      console.log('[前端-系统] dragleave事件触发');
      e.preventDefault();
      e.stopPropagation();
      fileUploadArea.style.borderColor = '#dee2e6';
      fileUploadArea.style.background = '#f8f9fa';
    });

    fileUploadArea.addEventListener('drop', (e) => {
      console.log('[前端-系统] drop事件触发');
      e.preventDefault();
      e.stopPropagation();
      fileUploadArea.style.borderColor = '#dee2e6';
      fileUploadArea.style.background = '#f8f9fa';

      const files = e.dataTransfer.files;
      console.log('[前端-系统] 拖拽文件数量:', files.length);

      if (files.length > 0) {
        console.log('[前端-系统] 设置文件到input元素');
        mediaFile.files = files;
        handleFileSelect({ target: { files } });
      }
    });

    fileUploadArea.addEventListener('click', () => {
      console.log('[前端-系统] 点击文件上传区域，触发文件选择');
      mediaFile.click();
    });
  }

  // 监听文件选择
  console.log('[前端-系统] 设置文件选择事件监听器');
  mediaFile.addEventListener('change', (e) => {
    handleFileSelect(e);
  });

  console.log('[前端-系统] 系统状态检查完成');
}

// 当前选择的文件
let selectedFile = null;

function handleFileSelect(e) {
  console.log('[前端-文件] 文件选择事件触发:', e);
  const file = e.target.files[0];
  if (file) {
    console.log('[前端-文件] 选择的文件信息:', {
      name: file.name,
      size: file.size,
      type: file.type,
      lastModified: new Date(file.lastModified).toISOString()
    });

    // 验证文件
    console.log('[前端-文件] 开始验证文件');
    if (!validateFile(file)) {
      return;
    }

    // 保存文件引用
    selectedFile = file;

    // 显示文件预览
    showFilePreview(file);

    // 启用开始按钮
    if (startBtn) startBtn.disabled = false;

    console.log('[前端-文件] 文件预览已显示');
  } else {
    console.log('[前端-文件] 未选择任何文件');
  }
}

// 显示文件预览
function showFilePreview(file) {
  const filePreviewCard = document.getElementById('filePreviewCard');
  const fileUploadArea = document.getElementById('fileUploadArea');
  const filePreviewName = document.getElementById('filePreviewName');
  const filePreviewSize = document.getElementById('filePreviewSize');
  const filePreviewType = document.getElementById('filePreviewType');
  const filePreviewDuration = document.getElementById('filePreviewDuration');
  const filePreviewIcon = document.getElementById('filePreviewIcon');
  const filePreviewThumbnail = document.getElementById('filePreviewThumbnail');

  // 显示预览卡片，隐藏上传区域
  if (filePreviewCard) filePreviewCard.classList.add('active');
  if (fileUploadArea) fileUploadArea.style.display = 'none';

  // 设置文件信息
  if (filePreviewName) filePreviewName.textContent = file.name;
  if (filePreviewSize) filePreviewSize.textContent = formatFileSize(file.size);
  if (filePreviewType) filePreviewType.textContent = file.type || '未知';

  // 设置图标
  if (filePreviewIcon) {
    if (file.type.startsWith('audio/')) {
      filePreviewIcon.className = 'fas fa-file-audio file-preview-icon audio';
    } else if (file.type.startsWith('video/')) {
      filePreviewIcon.className = 'fas fa-file-video file-preview-icon video';
    } else {
      filePreviewIcon.className = 'fas fa-file file-preview-icon';
    }
  }

  // 获取媒体时长和缩略图
  if (file.type.startsWith('audio/') || file.type.startsWith('video/')) {
    const url = URL.createObjectURL(file);
    const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio');
    media.src = url;

    media.onloadedmetadata = () => {
      const minutes = Math.floor(media.duration / 60);
      const seconds = Math.floor(media.duration % 60);
      const durationStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;
      if (filePreviewDuration) filePreviewDuration.textContent = durationStr;

      // 如果是视频，显示预览
      if (file.type.startsWith('video/') && filePreviewThumbnail) {
        filePreviewThumbnail.src = url;
        filePreviewThumbnail.classList.add('active');
      }

      console.log('[前端-文件] 媒体时长获取成功:', durationStr);
    };

    media.onerror = (error) => {
      console.error('[前端-文件] 获取媒体时长失败:', error);
      if (filePreviewDuration) filePreviewDuration.textContent = '未知';
    };
  }
}

// 删除文件预览
function clearFilePreview() {
  const filePreviewCard = document.getElementById('filePreviewCard');
  const fileUploadArea = document.getElementById('fileUploadArea');
  const filePreviewThumbnail = document.getElementById('filePreviewThumbnail');
  const mediaFile = document.getElementById('mediaFile');

  // 隐藏预览卡片，显示上传区域
  if (filePreviewCard) filePreviewCard.classList.remove('active');
  if (fileUploadArea) fileUploadArea.style.display = 'flex';

  // 清除缩略图
  if (filePreviewThumbnail) {
    filePreviewThumbnail.classList.remove('active');
    if (filePreviewThumbnail.src) {
      URL.revokeObjectURL(filePreviewThumbnail.src);
      filePreviewThumbnail.src = '';
    }
  }

  // 清除文件输入
  if (mediaFile) mediaFile.value = '';

  // 清除文件引用
  selectedFile = null;

  // 禁用开始按钮
  if (startBtn) startBtn.disabled = true;

  console.log('[前端-文件] 文件预览已清除');
}

// 显示文件预览
function showFilePreview(file) {
  const fileUploadArea = document.getElementById('fileUploadArea');
  const uploadPlaceholder = fileUploadArea.querySelector('.upload-placeholder');

  // 隐藏上传提示
  if (uploadPlaceholder) {
    uploadPlaceholder.style.display = 'none';
  }

  // 创建文件预览元素
  let filePreview = fileUploadArea.querySelector('.file-preview');
  if (!filePreview) {
    filePreview = document.createElement('div');
    filePreview.className = 'file-preview';
    filePreview.style.cssText = `
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 20px;
      background: white;
      border-radius: 8px;
      border: 1px solid #dee2e6;
    `;
    fileUploadArea.appendChild(filePreview);
  }

  // 文件信息
  const fileInfo = document.createElement('div');
  fileInfo.style.cssText = `
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 5px;
  `;

  const fileIcon = file.type.startsWith('video/') ? '🎬' : '🎵';

  fileInfo.innerHTML = `
    <div style="font-size: 2rem;">${fileIcon}</div>
    <div style="font-weight: 600; color: #333;">${file.name}</div>
    <div style="font-size: 0.85rem; color: #6c757d;">
      类型: ${file.type || '未知'} | 大小: ${formatFileSize(file.size)}
    </div>
    <div id="previewDuration" style="font-size: 0.85rem; color: #6c757d;">
      时长: 计算中...
    </div>
  `;

  // 删除按钮
  const deleteBtn = document.createElement('button');
  deleteBtn.innerHTML = '<i class="fas fa-times"></i>';
  deleteBtn.style.cssText = `
    background: #dc3545;
    color: white;
    border: none;
    border-radius: 50%;
    width: 36px;
    height: 36px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    transition: all 0.3s ease;
  `;

  deleteBtn.addEventListener('mouseover', () => {
    deleteBtn.style.background = '#c82333';
    deleteBtn.style.transform = 'scale(1.1)';
  });

  deleteBtn.addEventListener('mouseout', () => {
    deleteBtn.style.background = '#dc3545';
    deleteBtn.style.transform = 'scale(1)';
  });

  deleteBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearFileSelection();
  });

  // 清空并重新添加内容
  filePreview.innerHTML = '';
  filePreview.appendChild(fileInfo);
  filePreview.appendChild(deleteBtn);

  // 获取媒体时长
  if (file.type.startsWith('audio/') || file.type.startsWith('video/')) {
    const url = URL.createObjectURL(file);
    const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio');
    media.src = url;
    media.onloadedmetadata = () => {
      const minutes = Math.floor(media.duration / 60);
      const seconds = Math.floor(media.duration % 60);
      const durationStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;
      const durationEl = document.getElementById('previewDuration');
      if (durationEl) {
        durationEl.textContent = `时长: ${durationStr}`;
      }
      URL.revokeObjectURL(url);
    };
  }

  // 显示验证成功消息
  const validationMessage = document.getElementById('validationMessage');
  if (validationMessage) {
    validationMessage.innerHTML = '<div class="validation-success">✓ 文件验证通过，可以开始转换</div>';
  }

  // 启用开始按钮
  if (startBtn) startBtn.disabled = false;
}

// 清除文件选择
function clearFileSelection() {
  const mediaFile = document.getElementById('mediaFile');
  const fileUploadArea = document.getElementById('fileUploadArea');
  const uploadPlaceholder = fileUploadArea.querySelector('.upload-placeholder');
  const filePreview = fileUploadArea.querySelector('.file-preview');
  const validationMessage = document.getElementById('validationMessage');

  // 清空文件输入
  if (mediaFile) mediaFile.value = '';

  // 显示上传提示
  if (uploadPlaceholder) uploadPlaceholder.style.display = 'block';

  // 移除文件预览
  if (filePreview) filePreview.remove();

  // 清空验证消息
  if (validationMessage) validationMessage.innerHTML = '';

  // 禁用开始按钮
  if (startBtn) startBtn.disabled = true;

  console.log('[前端-文件] 文件选择已清除');
}

function validateFile(file) {
  const maxSize = 500 * 1024 * 1024; // 500MB
  const allowedTypes = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/mp4', 'audio/m4a', 'audio/aac', 'audio/flac',
    'video/mp4', 'video/avi', 'video/x-msvideo', 'video/quicktime',
    'video/x-matroska', 'video/webm'
  ];

  if (file.size > maxSize) {
    alert(`文件太大 (${formatFileSize(file.size)})，最大支持500MB`);
    return false;
  }

  if (!allowedTypes.includes(file.type) && !file.name.match(/\.(mp3|wav|m4a|mp4|avi|mov|mkv|flac)$/i)) {
    alert(`不支持的文件格式: ${file.type || '未知'}`);
    return false;
  }

  return true;
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function addCopyButtonToLiveSection() {
  // 在实时转写区域的标题旁添加复制全文和总结全文按钮
  const liveSection = document.querySelector('.live-transcript-section');
  if (liveSection) {
    const header = liveSection.querySelector('h3');
    if (header) {
      // 创建按钮容器
      const buttonContainer = document.createElement('div');
      buttonContainer.style.display = 'inline-block';
      buttonContainer.style.marginLeft = '10px';

      // 创建复制按钮
      const copyFullBtn = document.createElement('button');
      copyFullBtn.className = 'btn btn-secondary btn-small';
      copyFullBtn.innerHTML = '<i class="fas fa-copy"></i> 复制全文';
      copyFullBtn.style.marginRight = '5px';
      copyFullBtn.style.fontSize = '0.8rem';
      copyFullBtn.style.padding = '4px 8px';

      copyFullBtn.addEventListener('click', () => {
        // 收集所有实时转写文本（已经是清理后的文本）
        const allChunks = liveContainer.querySelectorAll('.chunk');
        let fullText = '';
        allChunks.forEach(chunk => {
          fullText += chunk.textContent + '\n';
        });

        if (fullText.trim()) {
          navigator.clipboard.writeText(fullText.trim()).then(() => {
            alert('实时转写全文已复制到剪贴板');
          }).catch(e => alert('复制失败: ' + e));
        } else {
          alert('暂无转写内容可复制');
        }
      });

      // 创建总结按钮
      const summarizeFullBtn = document.createElement('button');
      summarizeFullBtn.className = 'btn btn-primary btn-small';
      summarizeFullBtn.innerHTML = '<i class="fas fa-magic"></i> 总结全文';
      summarizeFullBtn.style.fontSize = '0.8rem';
      summarizeFullBtn.style.padding = '4px 8px';

      summarizeFullBtn.addEventListener('click', async () => {
        // 收集所有实时转写文本
        const allChunks = liveContainer.querySelectorAll('.chunk');
        let fullText = '';
        allChunks.forEach(chunk => {
          fullText += chunk.textContent + '\n';
        });

        if (!fullText.trim()) {
          alert('暂无转写内容可总结');
          return;
        }

        // 显示模型选择对话框
        const modelType = await showModelSelectionDialog();
        if (!modelType) return; // 用户取消

        // 禁用按钮并显示加载状态
        const originalText = summarizeFullBtn.innerHTML;
        summarizeFullBtn.disabled = true;
        summarizeFullBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 总结中...';

        try {
          // 调用总结API
          const response = await fetch('https://127.0.0.1:443/api/summarize', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              text: fullText.trim(),
              model_type: modelType
            })
          });

          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const data = await response.json();
          const summary = data.summary;

          // 显示总结结果
          showSummaryModal(summary);

        } catch (error) {
          console.error('AI总结失败:', error);
          alert('AI总结失败: ' + error.message);
        } finally {
          // 恢复按钮状态
          summarizeFullBtn.disabled = false;
          summarizeFullBtn.innerHTML = originalText;
        }
      });

      // 将按钮添加到容器中
      buttonContainer.appendChild(copyFullBtn);
      buttonContainer.appendChild(summarizeFullBtn);

      // 将容器添加到标题
      header.appendChild(buttonContainer);
    }
  }
}

// 显示模型选择对话框
function showModelSelectionDialog() {
  return new Promise((resolve) => {
    const modal = document.createElement('div');
    modal.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      justify-content: center;
      align-items: center;
      z-index: 1000;
    `;

    const modalContent = document.createElement('div');
    modalContent.style.cssText = `
      background: white;
      border-radius: 12px;
      padding: 20px;
      max-width: 400px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    `;

    const title = document.createElement('h3');
    title.textContent = '选择AI模型';
    title.style.cssText = `
      margin: 0 0 15px 0;
      color: #333;
    `;

    const description = document.createElement('p');
    description.textContent = '请选择用于总结的AI模型：';
    description.style.cssText = `
      margin: 0 0 15px 0;
      color: #666;
      font-size: 0.9rem;
    `;

    const modelSelect = document.createElement('select');
    modelSelect.style.cssText = `
      width: 100%;
      padding: 8px 12px;
      border: 1px solid #dee2e6;
      border-radius: 6px;
      font-size: 0.9rem;
      margin-bottom: 15px;
    `;
    modelSelect.innerHTML = `
      <option value="deepseek">DeepSeek Chat (云端，更强大)</option>
      <option value="ollama">Ollama Gemma3:4b (本地，更快速)</option>
    `;

    const actions = document.createElement('div');
    actions.style.cssText = `
      display: flex;
      gap: 10px;
      justify-content: flex-end;
    `;

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-secondary btn-small';
    cancelBtn.textContent = '取消';
    cancelBtn.style.fontSize = '0.8rem';
    cancelBtn.style.padding = '4px 8px';

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-primary btn-small';
    confirmBtn.textContent = '确定';
    confirmBtn.style.fontSize = '0.8rem';
    confirmBtn.style.padding = '4px 8px';

    cancelBtn.addEventListener('click', () => {
      document.body.removeChild(modal);
      resolve(null);
    });

    confirmBtn.addEventListener('click', () => {
      const selectedModel = modelSelect.value;
      document.body.removeChild(modal);
      resolve(selectedModel);
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);

    modalContent.appendChild(title);
    modalContent.appendChild(description);
    modalContent.appendChild(modelSelect);
    modalContent.appendChild(actions);

    modal.appendChild(modalContent);

    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        document.body.removeChild(modal);
        resolve(null);
      }
    });

    document.body.appendChild(modal);
  });
}

// 显示总结结果的模态框
function showSummaryModal(summary) {
  // 创建模态框元素
  const modal = document.createElement('div');
  modal.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
  `;

  const modalContent = document.createElement('div');
  modalContent.style.cssText = `
    background: white;
    border-radius: 12px;
    padding: 20px;
    max-width: 80%;
    max-height: 80%;
    overflow-y: auto;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    position: relative;
  `;

  const title = document.createElement('h3');
  title.textContent = 'AI总结结果';
  title.style.cssText = `
    margin: 0 0 15px 0;
    color: #333;
    display: flex;
    align-items: center;
    gap: 8px;
  `;

  const closeBtn = document.createElement('button');
  closeBtn.innerHTML = '<i class="fas fa-times"></i>';
  closeBtn.style.cssText = `
    position: absolute;
    top: 15px;
    right: 15px;
    background: none;
    border: none;
    font-size: 1.2rem;
    cursor: pointer;
    color: #666;
    padding: 5px;
  `;

  const summaryText = document.createElement('div');
  summaryText.className = 'ai-message-content';
  summaryText.style.cssText = `
    line-height: 1.6;
    background: #f8f9fa;
    padding: 15px;
    border-radius: 8px;
    border: 1px solid #dee2e6;
    margin-bottom: 15px;
    font-size: 0.9rem;
  `;

  // 使用marked.js渲染Markdown
  console.log('[总结Markdown] marked库状态:', typeof marked !== 'undefined' ? '已加载' : '未加载');
  console.log('[总结Markdown] 总结内容:', summary.substring(0, 100));

  if (typeof marked !== 'undefined') {
    marked.setOptions({
      breaks: true,
      gfm: true,
      headerIds: false,
      mangle: false
    });

    try {
      const renderedHtml = marked.parse(summary);
      console.log('[总结Markdown] 渲染后的HTML:', renderedHtml.substring(0, 100));
      summaryText.innerHTML = renderedHtml;

      // 应用代码高亮
      if (typeof hljs !== 'undefined') {
        summaryText.querySelectorAll('pre code').forEach((block) => {
          hljs.highlightElement(block);
        });
        console.log('[总结Markdown] 代码高亮已应用');
      }
    } catch (error) {
      console.error('[总结Markdown] 渲染错误:', error);
      summaryText.textContent = summary;
    }
  } else {
    console.warn('[总结Markdown] marked库未加载，使用纯文本显示');
    summaryText.textContent = summary;
  }

  const actions = document.createElement('div');
  actions.style.cssText = `
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  `;

  const copyBtn = document.createElement('button');
  copyBtn.className = 'btn btn-secondary btn-small';
  copyBtn.innerHTML = '<i class="fas fa-copy"></i> 复制总结';
  copyBtn.style.fontSize = '0.8rem';
  copyBtn.style.padding = '4px 8px';

  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(summary).then(() => {
      alert('总结已复制到剪贴板');
    }).catch(e => alert('复制失败: ' + e));
  });

  const downloadBtn = document.createElement('button');
  downloadBtn.className = 'btn btn-secondary btn-small';
  downloadBtn.innerHTML = '<i class="fas fa-download"></i> 下载总结';
  downloadBtn.style.fontSize = '0.8rem';
  downloadBtn.style.padding = '4px 8px';

  downloadBtn.addEventListener('click', () => {
    const blob = new Blob([summary], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '实时转写_AI总结_' + new Date().toISOString().slice(0, 19).replace(/:/g, '-') + '.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });

  // 组装模态框
  actions.appendChild(copyBtn);
  actions.appendChild(downloadBtn);

  modalContent.appendChild(title);
  modalContent.appendChild(closeBtn);
  modalContent.appendChild(summaryText);
  modalContent.appendChild(actions);

  modal.appendChild(modalContent);

  // 添加关闭事件
  closeBtn.addEventListener('click', () => {
    document.body.removeChild(modal);
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      document.body.removeChild(modal);
    }
  });

  // 显示模态框
  document.body.appendChild(modal);
}


// 聊天功能
let chatHistory = [];
let currentModel = 'deepseek';

function initChatFeature() {
  // 在实时转写区域下方添加聊天界面
  const liveSection = document.querySelector('.live-transcript-section');
  if (!liveSection) return;

  const chatSection = document.createElement('div');
  chatSection.className = 'chat-section';
  chatSection.style.cssText = `
    margin-top: 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  `;

  // 聊天标题和模型选择
  const chatHeader = document.createElement('div');
  chatHeader.style.cssText = `
    display: flex;
    justify-content: space-between;
    align-items: center;
  `;

  const chatTitle = document.createElement('h3');
  chatTitle.innerHTML = '<i class="fas fa-comments"></i> AI对话';
  chatTitle.style.cssText = `
    font-size: 1rem;
    color: #495057;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  `;

  const modelSelect = document.createElement('select');
  modelSelect.id = 'chatModelSelect';
  modelSelect.style.cssText = `
    padding: 4px 8px;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    font-size: 0.8rem;
    cursor: pointer;
  `;
  modelSelect.innerHTML = `
    <option value="deepseek">DeepSeek Chat</option>
    <option value="ollama">Ollama Gemma3:4b</option>
  `;
  modelSelect.addEventListener('change', (e) => {
    currentModel = e.target.value;
    console.log('切换模型到:', currentModel);
  });

  chatHeader.appendChild(chatTitle);
  chatHeader.appendChild(modelSelect);

  // 聊天消息容器
  const chatMessages = document.createElement('div');
  chatMessages.id = 'chatMessages';
  chatMessages.style.cssText = `
    background: #f8f9fa;
    border-radius: 8px;
    padding: 15px;
    border: 1px solid #dee2e6;
    min-height: 200px;
    max-height: 400px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
  `;

  // 输入区域
  const chatInputContainer = document.createElement('div');
  chatInputContainer.style.cssText = `
    display: flex;
    gap: 8px;
  `;

  const chatInput = document.createElement('input');
  chatInput.type = 'text';
  chatInput.id = 'chatInput';
  chatInput.placeholder = '输入问题...';
  chatInput.style.cssText = `
    flex: 1;
    padding: 8px 12px;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    font-size: 0.9rem;
  `;

  const chatSendBtn = document.createElement('button');
  chatSendBtn.className = 'btn btn-primary btn-small';
  chatSendBtn.innerHTML = '<i class="fas fa-paper-plane"></i> 发送';
  chatSendBtn.style.cssText = `
    padding: 8px 16px;
    font-size: 0.9rem;
  `;

  chatInputContainer.appendChild(chatInput);
  chatInputContainer.appendChild(chatSendBtn);

  // 组装聊天界面
  chatSection.appendChild(chatHeader);
  chatSection.appendChild(chatMessages);
  chatSection.appendChild(chatInputContainer);

  // 插入到实时转写区域的父容器
  liveSection.parentElement.appendChild(chatSection);

  // 绑定发送事件
  chatSendBtn.addEventListener('click', () => sendChatMessage());
  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      sendChatMessage();
    }
  });
}

async function sendChatMessage() {
  const chatInput = document.getElementById('chatInput');
  const chatMessages = document.getElementById('chatMessages');
  const message = chatInput.value.trim();

  if (!message) return;

  // 获取转写文本作为上下文
  const allChunks = liveContainer.querySelectorAll('.chunk');
  let context = '';
  allChunks.forEach(chunk => {
    context += chunk.textContent + '\n';
  });

  // 显示用户消息
  const userMessage = document.createElement('div');
  userMessage.style.cssText = `
    align-self: flex-end;
    background: #007bff;
    color: white;
    padding: 8px 12px;
    border-radius: 12px;
    max-width: 70%;
    word-wrap: break-word;
    font-size: 0.85rem;
  `;
  userMessage.textContent = message;
  chatMessages.appendChild(userMessage);

  // 清空输入框
  chatInput.value = '';

  // 显示加载状态
  const loadingMessage = document.createElement('div');
  loadingMessage.id = 'chatLoading';
  loadingMessage.style.cssText = `
    align-self: flex-start;
    background: #e9ecef;
    color: #6c757d;
    padding: 8px 12px;
    border-radius: 12px;
    max-width: 70%;
    font-size: 0.85rem;
  `;
  loadingMessage.innerHTML = '<i class="fas fa-spinner fa-spin"></i> AI思考中...';
  chatMessages.appendChild(loadingMessage);

  // 滚动到底部
  chatMessages.scrollTop = chatMessages.scrollHeight;

  try {
    // 构建消息历史
    const messages = [
      ...chatHistory,
      {
        role: 'user',
        content: message
      }
    ];

    // 调用聊天API
    const response = await fetch('https://127.0.0.1:443/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messages: messages,
        model_type: currentModel,
        context: context.trim(),
        temperature: 1.0
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    const aiResponse = data.response;

    // 移除加载状态
    chatMessages.removeChild(loadingMessage);

    // 显示AI回复（使用Markdown渲染）
    const aiMessage = document.createElement('div');
    aiMessage.className = 'ai-message-content';
    aiMessage.style.cssText = `
      align-self: flex-start;
      background: #e9ecef;
      color: #333;
      padding: 8px 12px;
      border-radius: 12px;
      max-width: 70%;
      word-wrap: break-word;
      font-size: 0.85rem;
      line-height: 1.6;
    `;

    // 使用marked.js渲染Markdown
    console.log('[Markdown] marked库状态:', typeof marked !== 'undefined' ? '已加载' : '未加载');
    console.log('[Markdown] AI回复内容:', aiResponse.substring(0, 100));

    if (typeof marked !== 'undefined') {
      // 配置marked选项
      marked.setOptions({
        breaks: true,  // 支持GFM换行
        gfm: true,     // 启用GitHub风格的Markdown
        headerIds: false,
        mangle: false
      });

      try {
        const renderedHtml = marked.parse(aiResponse);
        console.log('[Markdown] 渲染后的HTML:', renderedHtml.substring(0, 100));
        aiMessage.innerHTML = renderedHtml;

        // 应用代码高亮
        if (typeof hljs !== 'undefined') {
          aiMessage.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
          });
          console.log('[Markdown] 代码高亮已应用');
        }
      } catch (error) {
        console.error('[Markdown] 渲染错误:', error);
        aiMessage.textContent = aiResponse;
      }
    } else {
      console.warn('[Markdown] marked库未加载，使用纯文本显示');
      aiMessage.textContent = aiResponse;
    }

    chatMessages.appendChild(aiMessage);

    // 更新聊天历史
    chatHistory.push(
      { role: 'user', content: message },
      { role: 'assistant', content: aiResponse }
    );

    // 限制历史记录长度
    if (chatHistory.length > 20) {
      chatHistory = chatHistory.slice(-20);
    }

  } catch (error) {
    console.error('聊天失败:', error);
    chatMessages.removeChild(loadingMessage);

    const errorMessage = document.createElement('div');
    errorMessage.style.cssText = `
      align-self: flex-start;
      background: #f8d7da;
      color: #721c24;
      padding: 8px 12px;
      border-radius: 12px;
      max-width: 70%;
      font-size: 0.85rem;
    `;
    errorMessage.textContent = '发送失败: ' + error.message;
    chatMessages.appendChild(errorMessage);
  }

  // 滚动到底部
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// =====================================================
// 批量处理逻辑
// =====================================================

let batchSocket = null;

// 初始化Socket连接
function initBatchSocket() {
  if (batchSocket) return;

  if (typeof io !== 'undefined') {
    console.log('[前端-批处理] 初始化Socket.IO连接...');
    batchSocket = io();

    batchSocket.on('connect', () => {
      console.log('[前端-批处理] Socket已连接');
    });

    batchSocket.on('batch_log', (data) => {
      const consoleEl = document.getElementById('batch-console');
      if (consoleEl) {
        const entry = document.createElement('div');
        entry.className = `log-entry ${data.level || 'info'}`;

        // 简单的颜色映射
        if (data.level === 'error') entry.style.color = '#dc3545';
        if (data.level === 'success') entry.style.color = '#28a745';
        if (data.level === 'warning') entry.style.color = '#ffc107';

        entry.textContent = `[${new Date().toLocaleTimeString()}] ${data.message}`;
        consoleEl.appendChild(entry);
        consoleEl.scrollTop = consoleEl.scrollHeight;
      }
    });

    batchSocket.on('batch_progress', (data) => {
      const fill = document.getElementById('batch-progress-fill');
      const percent = document.getElementById('batch-progress-percent');
      const text = document.getElementById('batch-progress-text');
      const currentFile = document.getElementById('batch-current-file');

      if (fill) fill.style.width = data.percent + '%';
      if (percent) percent.textContent = data.percent + '%';
      if (text) text.textContent = `正在处理: ${data.current}/${data.total}`;
      if (currentFile) currentFile.textContent = data.current_file;
    });

    batchSocket.on('batch_complete', (data) => {
      const text = document.getElementById('batch-progress-text');
      const fill = document.getElementById('batch-progress-fill');
      const btn = document.getElementById('btn-start-batch');

      if (text) text.textContent = '所有处理完成！';
      if (fill) fill.style.width = '100%';

      alert(`批量处理完成！\n输出目录: ${data.output_folder}`);
      if (btn) btn.disabled = false;
    });
  } else {
    console.error('[前端-批处理] Socket.IO 库未加载，无法接收进度');
  }
}

// 切换模式
window.switchMode = function (mode) {
  const singleTab = document.getElementById('tab-single');
  const batchTab = document.getElementById('tab-batch');
  const singleMode = document.getElementById('single-mode');
  const batchMode = document.getElementById('batch-mode');

  if (mode === 'single') {
    singleTab.classList.add('active');
    singleTab.style.borderBottom = '2px solid #007bff';
    singleTab.style.color = '#007bff';

    batchTab.classList.remove('active');
    batchTab.style.borderBottom = 'none';
    batchTab.style.color = '#666';

    singleMode.style.display = 'block';
    batchMode.style.display = 'none';
  } else {
    batchTab.classList.add('active');
    batchTab.style.borderBottom = '2px solid #007bff';
    batchTab.style.color = '#007bff';

    singleTab.classList.remove('active');
    singleTab.style.borderBottom = 'none';
    singleTab.style.color = '#666';

    singleMode.style.display = 'none';
    batchMode.style.display = 'block';

    // 切换到批量模式时初始化Socket
    initBatchSocket();
  }
}

// 打开文件夹选择器
window.selectBatchFolder = async function (type) {
  try {
    const resp = await fetch('/api/select-folder');
    const data = await resp.json();
    if (data.path) {
      if (type === 'input') {
        document.getElementById('batch-input-path').value = data.path;
      } else {
        document.getElementById('batch-output-path').value = data.path;
      }
    } else if (data.error) {
      alert('选择文件夹出错: ' + data.error);
    }
  } catch (e) {
    console.error(e);
    alert('无法连接到服务器打开对话框');
  }
}

// 开始批量处理
window.startBatchProcess = async function () {
  const inputFolder = document.getElementById('batch-input-path').value;
  const outputFolder = document.getElementById('batch-output-path').value;
  const device = document.getElementById('batch-device').value;
  const duration = document.getElementById('batch-segment-duration').value;
  const skipExisting = document.getElementById('batch-skip-existing').checked;
  const skipRecognized = document.getElementById('batch-skip-recognized').checked;

  if (!inputFolder) {
    alert('请选择或输入包含媒体文件的输入文件夹');
    return;
  }

  // UI状态更新
  document.getElementById('batch-status-section').style.display = 'block';
  document.getElementById('btn-start-batch').disabled = true;
  document.getElementById('batch-console').innerHTML = '<div class="log-entry info">正在启动批量处理任务...</div>';

  // 初始化Socket确保连接
  initBatchSocket();

  try {
    const resp = await fetch('/api/batch-process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_folder: inputFolder,
        output_folder: outputFolder,
        device: device,
        segment_duration: duration,
        skip_existing: skipExisting,
        skip_recognized: skipRecognized
      })
    });

    const data = await resp.json();

    if (!resp.ok) {
      alert('启动失败: ' + (data.error || '未知错误'));
      document.getElementById('btn-start-batch').disabled = false;
    } else {
      console.log('Batch started, task_id:', data.task_id);
    }
  } catch (e) {
    alert('请求失败: ' + e);
    document.getElementById('btn-start-batch').disabled = false;
  }
}
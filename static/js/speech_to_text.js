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
function appendLive(text, isFinal=false) {
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
  return text
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
}

// ----- 绑定事件监听器 -----
function bindEvents() {
  // 折叠面板事件监听器
  console.log('[前端-事件] 设置折叠面板事件监听器');
  const fileInfoToggle = document.getElementById('fileInfoToggle');
  const processingOptionsToggle = document.getElementById('processingOptionsToggle');

  if (fileInfoToggle) {
    fileInfoToggle.addEventListener('click', function() {
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
    processingOptionsToggle.addEventListener('click', function() {
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
    currentTaskId = 'client-' + Date.now() + '-' + Math.random().toString(36).slice(2,8);
    console.log('[前端-按钮] 生成客户端task_id:', currentTaskId);

    const file = mediaFile.files[0];
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
      const resp = await fetch('/api/speech-to-text', { method: 'POST', body: form });
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
  downloadLink.href = `/api/streaming-speech-result/${currentTaskId}`;
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

    // 更新文件信息显示
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    const fileSize = document.getElementById('fileSize');
    const fileType = document.getElementById('fileType');
    const fileDuration = document.getElementById('fileDuration');

    if (fileName) fileName.textContent = file.name;
    if (fileSize) fileSize.textContent = formatFileSize(file.size);
    if (fileType) fileType.textContent = file.type || '未知';

    if (fileInfo) fileInfo.style.display = 'block';

    console.log('[前端-文件] 文件信息已更新到UI');

    // 获取媒体时长
    if (file.type.startsWith('audio/') || file.type.startsWith('video/')) {
      console.log('[前端-文件] 开始获取媒体时长');
      const url = URL.createObjectURL(file);
      const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio');
      media.src = url;
      media.onloadedmetadata = () => {
        const minutes = Math.floor(media.duration / 60);
        const seconds = Math.floor(media.duration % 60);
        const durationStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        if (fileDuration) fileDuration.textContent = durationStr;
        console.log('[前端-文件] 媒体时长获取成功:', durationStr, '总秒数:', media.duration);
        URL.revokeObjectURL(url);
      };
      media.onerror = (error) => {
        console.error('[前端-文件] 获取媒体时长失败:', error);
      };
    } else {
      console.log('[前端-文件] 非媒体文件，跳过时长获取');
    }

    // 验证文件
    console.log('[前端-文件] 开始验证文件');
    validateFile(file);
  } else {
    console.log('[前端-文件] 未选择任何文件');
  }
}

function validateFile(file) {
  const maxSize = 500 * 1024 * 1024; // 500MB
  const allowedTypes = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/mp4', 'audio/m4a', 'audio/aac', 'audio/flac',
    'video/mp4', 'video/avi', 'video/x-msvideo', 'video/quicktime',
    'video/x-matroska', 'video/webm'
  ];

  const validationMessage = document.getElementById('validationMessage');

  let isValid = true;
  let message = '';

  if (file.size > maxSize) {
    isValid = false;
    message = '文件大小超过500MB限制';
  } else if (!allowedTypes.includes(file.type) && !file.name.match(/\.(mp3|wav|m4a|mp4|avi|mov|mkv|flac)$/i)) {
    isValid = false;
    message = '不支持的文件格式';
  } else {
    message = '文件格式和大小验证通过';
    if (startBtn) startBtn.disabled = false;
  }

  if (validationMessage) {
    validationMessage.innerHTML = `<div class="${isValid ? 'validation-success' : 'validation-error'}">${message}</div>`;
  }

  return isValid;
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function addCopyButtonToLiveSection() {
  // 在实时转写区域的标题旁添加复制全文按钮
  const liveSection = document.querySelector('.live-transcript-section');
  if (liveSection) {
    const header = liveSection.querySelector('h3');
    if (header) {
      // 创建复制按钮
      const copyFullBtn = document.createElement('button');
      copyFullBtn.className = 'btn btn-secondary btn-small';
      copyFullBtn.innerHTML = '<i class="fas fa-copy"></i> 复制全文';
      copyFullBtn.style.marginLeft = '10px';
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

      header.appendChild(copyFullBtn);
    }
  }
}

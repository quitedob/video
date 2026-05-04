// 前端示例: static/js/speech-client.js
// 备注：在页面加载时建立 socket 连接，监听后端事件
const socket = io('/');

socket.on('connect', () => {
  console.log('socket connected');
});

function startASR(taskId) {
  // 向后端发起请求（如 POST /api/speech-to-text），后端通过 socket 推进进度
  showStatus('等待中...');
}

socket.on('asr:started', (data) => {
  showStatus('开始处理...');
});

socket.on('asr:progress', (data) => {
  // data e.g. {percent: 23, message: "VAD 切分中"}
  updateProgressBar(data.percent, data.message);
});

socket.on('asr:done', (data) => {
  showStatus('处理完成');
  showResultText(data.text); // data.text 为识别到的字符串
});

socket.on('asr:error', (err) => {
  showStatus('出错：' + err.message);
});

// 示例函数定义（需要您在 HTML 中实现这些函数）
function showStatus(message) {
  // 更新状态显示
  const statusElement = document.getElementById('status');
  statusElement.textContent = message;
}

function updateProgressBar(percent, message) {
  // 更新进度条
  const progressBar = document.getElementById('progressBar');
  const progressText = document.getElementById('progressText');

  progressBar.style.width = percent + '%';
  progressText.textContent = message;
}

function showResultText(text) {
  // 显示识别结果
  const resultElement = document.getElementById('result');
  resultElement.textContent = text;
  resultElement.style.display = 'block';
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', function() {
  console.log('语音转文字前端初始化完成');

  // 绑定开始按钮
  const startButton = document.getElementById('startButton');
  if (startButton) {
    startButton.addEventListener('click', function() {
      startASR('speech-task-' + Date.now());
    });
  }
});

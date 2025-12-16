
import threading
import time
import psutil
import logging
import torch
from typing import Optional, Any

logger = logging.getLogger(__name__)

class SystemMonitor(threading.Thread):
    def __init__(self, interval: float = 2.0, task_id: Optional[str] = None, socketio: Optional[Any] = None):
        super().__init__(daemon=True)
        self.interval = interval
        self.task_id = task_id
        self.socketio = socketio
        self.stop_event = threading.Event()
        self.gpu_available = torch.cuda.is_available()
        self.device_name = torch.cuda.get_device_name(0) if self.gpu_available else "CPU"
        
        if self.gpu_available:
            try:
                # 尝试预热 CUDA 以确保统计准确
                 torch.cuda.memory_allocated()
            except:
                pass

    def run(self):
        logger.info(f"系统资源监控已启动 (设备: {self.device_name})")
        while not self.stop_event.is_set():
            try:
                stats = self._get_stats()
                self._print_stats(stats)
                if self.socketio and self.task_id:
                    self._emit_stats(stats)
            except Exception as e:
                logger.error(f"监控出错: {e}")
            
            time.sleep(self.interval)
        logger.info("系统资源监控已停止")

    def stop(self):
        self.stop_event.set()
        self.join(timeout=2.0)

    def _get_stats(self):
        # 系统内存
        vm = psutil.virtual_memory()
        ram_used_gb = vm.used / (1024 ** 3)
        ram_total_gb = vm.total / (1024 ** 3)
        ram_percent = vm.percent

        stats = {
            'timestamp': time.time(),
            'ram_used_gb': ram_used_gb,
            'ram_total_gb': ram_total_gb,
            'ram_percent': ram_percent,
            'gpu_available': self.gpu_available,
        }

        # GPU 显存
        if self.gpu_available:
            try:
                gpu_allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
                gpu_reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
                # 获取总显存（使用属性或 pynvml，这里简单用 torch.cuda.get_device_properties）
                props = torch.cuda.get_device_properties(0)
                gpu_total = props.total_memory / (1024 ** 3)
                
                stats['gpu_allocated_gb'] = gpu_allocated
                stats['gpu_reserved_gb'] = gpu_reserved
                stats['gpu_total_gb'] = gpu_total
            except Exception:
                stats['gpu_error'] = True

        return stats

    def _print_stats(self, stats):
        if stats['gpu_available']:
            allocated = stats.get('gpu_allocated_gb', 0)
            reserved = stats.get('gpu_reserved_gb', 0)
            total = stats.get('gpu_total_gb', 0)
            msg = (
                f"[资源监控] GPU显存: {allocated:.2f}GB / {total:.2f}GB (预留: {reserved:.2f}GB) | "
                f"系统内存: {stats['ram_used_gb']:.2f}GB / {stats['ram_total_gb']:.2f}GB ({stats['ram_percent']}%)"
            )
        else:
            msg = (
                f"[资源监控] CPU模式 | "
                f"系统内存: {stats['ram_used_gb']:.2f}GB / {stats['ram_total_gb']:.2f}GB ({stats['ram_percent']}%)"
            )
        # 直接打印到控制台，确保后端可见
        print(msg)

    def _emit_stats(self, stats):
        try:
            self.socketio.emit('system_stats', {
                'task_id': self.task_id,
                'stats': stats
            }, namespace='/')
        except Exception:
            pass

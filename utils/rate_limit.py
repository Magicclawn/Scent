import time


class AdaptiveRateLimiter:
    def __init__(self, error_threshold=0.30, recovery_threshold=0.05, cooldown=2.0, step_up=0.1, step_down_factor=1.5, max_penalty=5.0):
        self.penalty_delay = 0.0 # 延迟惩罚
        self._window_size = 100
        self._error_rate = 0.0
        self.error_threshold = error_threshold # > 30% 降速
        self.recovery_threshold = recovery_threshold # < 5% 恢复
        self.cooldown = cooldown # 调整后冷却秒数
        self.step_up = step_up # 恢复时每次减 0.1s
        self.step_down_factor = step_down_factor # 降速时乘以1.5
        self.max_penalty = max_penalty # 惩罚上限
        self._last_adjust_time = time.time()


    def record(self, status):
        is_error = 1 if (status is None or status in (429, 503)) else 0
        alpha = 2 / (self._window_size + 1)
        self._error_rate = alpha * is_error + (1 - alpha) * self._error_rate

    def should_step_down(self):
        cool_time = time.time() - self._last_adjust_time
        if self._error_rate >= self.error_threshold and cool_time > self.cooldown:
            return True
        return False

    def should_step_up(self):
        cool_time = time.time() - self._last_adjust_time
        if self._error_rate < self.recovery_threshold and cool_time > self.cooldown and self.penalty_delay > 0:
            return True
        return False

    def step_up(self):
        self.penalty_delay = max(self.penalty_delay - self.step_up, 0)
        self._last_adjust_time = time.time()
        return self.penalty_delay

    def step_down(self):
        if self.penalty_delay < 0.05:
            new_delay = 0.2  # 起步值，避免 0×1.5=0
        else:
            new_delay = self.penalty_delay * self.step_down_factor
        self.penalty_delay = min(new_delay, self.max_penalty)
        self._last_adjust_time = time.time()
        return self.penalty_delay


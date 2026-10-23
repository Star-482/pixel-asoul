<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
  seconds: { type: Number, default: 0 },
});
const emit = defineEmits(['close']);

const remaining = ref(0);
let countdownInterval = null;

const formattedTime = computed(() => {
  const total = Math.max(0, remaining.value);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes > 0 ? `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒` : `${seconds} 秒`;
});

watch(
  () => props.seconds,
  (value) => {
    if (!value || value <= 0) return;
    remaining.value = Math.floor(value);
    clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
      remaining.value--;
      if (remaining.value <= 0) {
        clearInterval(countdownInterval);
        countdownInterval = null;
        emit('close');
      }
    }, 1000);
  },
  { immediate: true }
);

onBeforeUnmount(() => clearInterval(countdownInterval));
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="seconds > 0" class="modal-backdrop" @click.self="emit('close')">
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-label="覆盖冷却提示">
          <div class="modal-icon">⚠</div>
          <h3 class="modal-title">请勿覆盖他人作品</h3>
          <p class="modal-text">
            检测到高频覆盖操作，覆盖功能已暂时冷却。
            如是恢复自己的作品，请联系站长协助处理。
          </p>
          <div class="modal-cooldown">
            <span class="cooldown-label">覆盖冷却剩余</span>
            <span class="cooldown-time">{{ formattedTime }}</span>
          </div>
          <a
            class="modal-link"
            href="https://space.bilibili.com/259253013"
            target="_blank"
            rel="noopener noreferrer"
          >
            联系站长（哔哩哔哩主页）
          </a>
          <p class="modal-hint">冷却期间仍可在空白区域绘制。</p>
          <button class="modal-close" @click="emit('close')">我知道了</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(2px);
}

.modal-dialog {
  width: min(92vw, 360px);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: 24px;
  text-align: center;
}

.modal-icon {
  font-size: 32px;
  line-height: 1;
  margin-bottom: 10px;
}

.modal-title {
  margin: 0 0 10px;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}

.modal-text {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.modal-cooldown {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px;
  border-radius: var(--radius-sm);
  background: rgba(245, 158, 11, 0.1);
  margin-bottom: 14px;
}

.cooldown-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.cooldown-time {
  font-size: 15px;
  font-weight: 700;
  color: var(--warning);
  font-variant-numeric: tabular-nums;
}

.modal-link {
  display: block;
  color: #00AEEC;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
}

.modal-link:hover {
  color: #0083b0;
}

.modal-hint {
  margin: 0 0 16px;
  font-size: 12px;
  color: var(--text-secondary);
}

.modal-close {
  width: 100%;
  padding: 10px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--primary);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: opacity var(--transition);
}

.modal-close:hover {
  opacity: 0.9;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>

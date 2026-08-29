<script setup>
import { inject } from 'vue';

const props = defineProps({
  selectedColor: { type: String, required: true },
  cooldownSeconds: { type: Number, default: 0 },
  isCrosshairMode: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
  crosshairCoord: { type: Object, default: null }
});

const emit = defineEmits(['open-color-picker', 'place-pixel', 'pick-color', 'toggle-crosshair']);

const showToast = inject('showToast');

function handlePlace() {
  if (props.disabled) {
    showToast?.('当前画布仅允许浏览', 'warning');
    return;
  }
  if (props.cooldownSeconds > 0) {
    showToast?.(`冷却中，请等待 ${props.cooldownSeconds} 秒`, 'warning');
    return;
  }
  if (!props.isCrosshairMode) {
    showToast?.('请开启准星模式以精确放置', 'warning');
    return;
  }
  emit('place-pixel');
}

function handlePickColor() {
  if (!props.isCrosshairMode) {
    showToast?.('请先开启准星模式，再从画布取色', 'warning');
    return;
  }
  emit('pick-color');
}
</script>

<template>
  <div class="mobile-toolbar">
    <div class="left-tools">
      <!-- 画布内取色，不依赖浏览器的 EyeDropper API。 -->
      <button
        class="tool-btn eyedropper-btn"
        @click="handlePickColor"
        aria-label="从画布取色"
        title="从准星位置取色"
      >
        <span class="icon">🔍</span>
      </button>

      <!-- 颜色选择器入口 -->
      <button
        class="tool-btn color-btn"
        :style="{ backgroundColor: selectedColor || '#ffffff' }"
        @click="$emit('open-color-picker')"
        aria-label="打开颜色选择器"
      >
        <span class="icon">🎨</span>
      </button>
    </div>

    <!-- 放置像素主按钮 -->
    <button
      class="place-btn"
      :class="{ cooling: cooldownSeconds > 0, disabled }"
      :disabled="disabled || cooldownSeconds > 0"
      @click="handlePlace"
    >
      <span class="place-icon">✏️</span>
      <span class="place-text">
        {{ disabled ? '仅浏览' : cooldownSeconds > 0 ? `冷却 ${cooldownSeconds}s` : '放置像素' }}
      </span>
    </button>

    <!-- 当前准星坐标 -->
    <div class="coord-display">
      <span v-if="crosshairCoord">
        ({{ crosshairCoord.x }}, {{ crosshairCoord.y }})
      </span>
      <span v-else class="coord-empty">--</span>
    </div>

    <!-- 准星开关 -->
    <button
      class="tool-btn crosshair-btn"
      :class="{ active: isCrosshairMode }"
      @click="$emit('toggle-crosshair')"
      aria-label="切换准星模式"
    >
      <span class="icon">🎯</span>
    </button>
  </div>
</template>

<style scoped>
.mobile-toolbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid var(--border, #e2e8f0);
  z-index: 200;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.08);
}

.left-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 2px solid var(--border, #e2e8f0);
  background: var(--bg-card, #ffffff);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: var(--shadow, 0 1px 3px rgba(0, 0, 0, 0.1));
}

.tool-btn:active {
  transform: scale(0.95);
}

.color-btn {
  border-color: var(--selected-color, #e2e8f0);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.8), 0 2px 8px rgba(0, 0, 0, 0.15);
}

.icon {
  font-size: 20px;
  line-height: 1;
}

.place-btn {
  flex: 1;
  height: 46px;
  min-width: 100px;
  max-width: 240px;
  border: none;
  border-radius: 23px;
  background: linear-gradient(135deg, var(--primary, #6366f1), var(--primary-hover, #4f46e5));
  color: white;
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
  transition: all 0.2s ease;
  white-space: nowrap;
  padding: 0 16px;
}

.place-btn:active {
  transform: scale(0.98);
}

.place-btn.cooling {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35);
  cursor: not-allowed;
}

.place-btn.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.place-icon {
  font-size: 16px;
}

.crosshair-btn.active {
  border-color: var(--primary, #6366f1);
  background: var(--primary-light, #e0e7ff);
}

.coord-display {
  min-width: 62px;
  padding: 5px 8px;
  background: rgba(30, 41, 59, 0.85);
  color: #fff;
  border-radius: 12px;
  font-size: 11px;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  text-align: center;
  flex-shrink: 0;
}

.coord-empty {
  opacity: 0.6;
}

@media (max-width: 380px) {
  .mobile-toolbar {
    gap: 6px;
    padding: 8px;
  }

  .left-tools {
    gap: 6px;
  }

  .tool-btn {
    width: 40px;
    height: 40px;
  }

  .icon {
    font-size: 18px;
  }

  .place-btn {
    min-width: 76px;
    height: 42px;
    font-size: 13px;
    padding: 0 10px;
  }

  .coord-display {
    min-width: 54px;
    padding: 4px 6px;
    font-size: 10px;
  }
}
</style>

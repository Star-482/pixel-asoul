<script setup>
import { ref, onMounted, onBeforeUnmount, provide } from 'vue';
import CanvasBoard from './components/CanvasBoard.vue';
import ColorPicker from './components/ColorPicker.vue';
import CooldownTimer from './components/CooldownTimer.vue';
import MobileToolbar from './components/MobileToolbar.vue';
import FloatingToolbar from './components/FloatingToolbar.vue';
import OverwriteCooldownModal from './components/OverwriteCooldownModal.vue';
import ws from './utils/ws.js';

// 状态管理
const selectedColor = ref('#FF0000');
const canvasBoard = ref(null);
const cooldownTimer = ref(null);
const drawEnabled = ref(false);
const overwriteCooldown = ref(0);

// 移动端状态
const isMobile = ref(false);
const isColorPickerOpen = ref(false);
const isCrosshairMode = ref(true);
const isInfoOpen = ref(false);
const mobileCooldown = ref(0);
const crosshairCoord = ref(null);
let mobileCooldownTimer = null;

// 统计信息
const stats = ref({
  onlineCount: 0,
  totalVisits: 0,
  totalPixels: 0
});

// Toast 通知
const toasts = ref([]);
let toastId = 0;

function showToast(message, type = 'warning', duration = 3000) {
  const id = ++toastId;
  toasts.value.push({ id, message, type });
  setTimeout(() => {
    toasts.value = toasts.value.filter(t => t.id !== id);
  }, duration);
}

function handleServerError(message) {
  const data = message.data || {};

  // Overwrite cooling gets a dedicated modal: the message asks the visitor to
  // respect others' work and points at the owner's contact page.
  if (data.code === 'destructive_cooldown') {
    overwriteCooldown.value = Math.max(1, Math.floor(data.retry_after || 0));
    return;
  }

  showToast(data.message || '操作过于频繁，请稍后再试', 'warning');

  // Rate limits and a temporary drawing block apply to every placement.
  const blocksAllDrawing = data.code === 'rate_limited' || data.code === 'drawing_blocked';
  if (blocksAllDrawing && data.retry_after) {
    if (isMobile.value) {
      startMobileCooldown(data.retry_after);
    } else if (cooldownTimer.value) {
      cooldownTimer.value.startCooldown(data.retry_after);
    }
  }
}

const cooldownEventBus = {
  listeners: [],
  emit(data) {
    this.listeners.forEach(callback => callback(data))
  },
  on(callback) {
    this.listeners.push(callback)
  },
  off(callback) {
    this.listeners = this.listeners.filter(cb => cb !== callback)
  }
}
provide('cooldownEventBus', cooldownEventBus)
provide('showToast', showToast)

function checkMobile() {
  const mq = window.matchMedia('(max-width: 639px), (hover: none) and (pointer: coarse)');
  isMobile.value = mq.matches;
}

function startMobileCooldown(seconds) {
  stopMobileCooldown();
  mobileCooldown.value = Math.max(0, Math.floor(seconds));
  if (mobileCooldown.value <= 0) return;

  mobileCooldownTimer = setInterval(() => {
    mobileCooldown.value--;
    if (mobileCooldown.value <= 0) {
      stopMobileCooldown();
      cooldownEventBus.emit({ type: 'cooldown-end' });
    }
  }, 1000);
}

function stopMobileCooldown() {
  if (mobileCooldownTimer) {
    clearInterval(mobileCooldownTimer);
    mobileCooldownTimer = null;
  }
}

// 连接到WebSocket服务器
onMounted(() => {
  //移除H1
  const seoH1 = document.getElementById('seo-h1')
  if (seoH1) seoH1.remove()

  checkMobile();
  window.matchMedia('(max-width: 639px), (hover: none) and (pointer: coarse)').addEventListener('change', checkMobile);

  const wsUrl = window.location.protocol === 'https:'
    ? `wss://${window.location.host}/ws/canvas`
    : `ws://${window.location.host}/ws/canvas`;
  ws.connect(wsUrl);

  ws.on('session.ready', (message) => {
    const data = message.data?.stats || {};
    stats.value = {
      onlineCount: data.online_users || 0,
      totalVisits: data.total_visits || 0,
      totalPixels: data.total_placed_pixels || 0
    };
  });

  // V2 errors contain the retry interval and the originating request id.
  ws.on('server_error', handleServerError);

  // 监听统计信息更新
  ws.on('stats', (data) => {
    stats.value = {
      onlineCount: data.online_users || 0,
      totalVisits: data.total_visits || 0,
      totalPixels: data.total_placed_pixels || 0
    };
  });

  ws.on('pixel.updated', (message) => {
    if (typeof message.data?.total_placed_pixels === 'number') {
      stats.value.totalPixels = message.data.total_placed_pixels;
    }
  });
})

onBeforeUnmount(() => {
  stopMobileCooldown();
  ws.off('server_error', handleServerError);
  window.matchMedia('(max-width: 639px), (hover: none) and (pointer: coarse)').removeEventListener('change', checkMobile);
});

// 重置画布视图
function resetCanvasView() {
  if (canvasBoard.value) {
    canvasBoard.value.resetView();
  }
}

function zoomIn() {
  canvasBoard.value?.zoomIn();
}

function zoomOut() {
  canvasBoard.value?.zoomOut();
}

function toggleCrosshair() {
  isCrosshairMode.value = !isCrosshairMode.value;
}

function openColorPicker() {
  isColorPickerOpen.value = true;
}

function closeColorPicker() {
  isColorPickerOpen.value = false;
}

function toggleInfo() {
  isInfoOpen.value = !isInfoOpen.value;
}

function handlePlacePixel() {
  if (!drawEnabled.value) {
    showToast('当前画布仅允许浏览', 'warning');
    return;
  }
  const ok = canvasBoard.value?.placeAtCrosshair();
  if (!ok) {
    showToast('请将准星对准画布内再放置', 'warning');
  }
}

function handlePickColor() {
  const picked = canvasBoard.value?.pickAtCrosshair();
  if (!picked) {
    showToast('画布尚未加载完成，或准星未对准画布内', 'warning');
    return;
  }
  selectedColor.value = picked.color;
  showToast(`已从画布取色 ${picked.color}`, 'success');
}
</script>

<template>
  <div class="app">
    <!-- Toast 通知 -->
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast-item"
          :class="toast.type"
        >
          <span class="toast-icon">{{ toast.type === 'warning' ? '⚠' : toast.type === 'error' ? '✕' : '✓' }}</span>
          <span class="toast-message">{{ toast.message }}</span>
        </div>
      </TransitionGroup>
    </div>

    <!-- 顶部导航 -->
    <header class="app-header" :class="{ mobile: isMobile }">
      <div class="header-left">
        <div class="logo">
          <img src="./assets/icon.png" alt="A手像素画板" class="logo-img" />
          <div class="logo-text">
            <h1 class="title" :class="{ mobile: isMobile }">A手像素画板</h1>
            <p v-if="!isMobile" class="subtitle">多人在线像素艺术协作平台</p>
          </div>
        </div>
      </div>
      <div class="header-right">
        <div class="stats-bar">
          <div class="stat-chip">
            <span class="stat-dot online"></span>
            <span class="stat-num">{{ stats.onlineCount }}</span>
            <span class="stat-label">在线</span>
          </div>
          <div class="stat-chip">
            <span class="stat-dot visits"></span>
            <span class="stat-num">{{ stats.totalVisits }}</span>
            <span class="stat-label">访问</span>
          </div>
          <div class="stat-chip">
            <span class="stat-dot pixels"></span>
            <span class="stat-num">{{ stats.totalPixels }}</span>
            <span class="stat-label">像素</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 桌面端布局 -->
    <div v-if="!isMobile" class="main-container">
      <!-- 左侧工具面板 -->
      <aside class="panel panel-left">
        <ColorPicker v-model="selectedColor" />
        <CooldownTimer ref="cooldownTimer" />
        <button @click="resetCanvasView" class="reset-view-btn">
          <span class="btn-icon">↻</span>
          重置视图
        </button>
      </aside>

      <!-- 中间画布区域 -->
      <main class="canvas-area">
        <CanvasBoard
          ref="canvasBoard"
          :selected-color="selectedColor"
          :is-mobile="false"
          @draw-enabled="drawEnabled = $event"
          @pixel-placed="() => {}"
        />
      </main>

      <!-- 右侧信息面板 -->
      <aside class="panel panel-right">
        <div class="card">
          <h3 class="card-title">使用说明</h3>
          <ul class="guide-list">
            <li><span class="guide-key">选色</span> 左侧选择颜色</li>
            <li><span class="guide-key">绘制</span> 点击画布放置像素</li>
            <li><span class="guide-key">缩放</span> 鼠标滚轮缩放</li>
            <li><span class="guide-key">移动</span> 按住鼠标拖拽</li>
            <li><span class="guide-key">协作</span> 与其他用户实时创作</li>
          </ul>
          <div class="tip-box">
            桌面端吸管可从屏幕取色；不支持时可直接使用调色板或输入颜色。
          </div>
          <div class="tip-box collaboration-tip">
            <strong>共同创作提醒</strong>
            请尊重已有作品，请勿无意义覆盖、涂抹或破坏他人的创作。
          </div>
        </div>

        <div class="card bili-card">
          <div class="bili-link">
            <img src="./assets/bilibili_play.png" alt="Bilibili" class="bili-icon" />
            <a href="https://www.bilibili.com/video/BV1wscrz3ERL" target="_blank" rel="noopener noreferrer">
              绘画过程可视化
            </a>
          </div>
          <div class="bili-link">
            <img src="./assets/bilibili_play.png" alt="Bilibili" class="bili-icon" />
            <a href="https://space.bilibili.com/259253013" target="_blank" rel="noopener noreferrer">
              联系站长
            </a>
          </div>
        </div>
      </aside>
    </div>

    <!-- 移动端布局 -->
    <template v-else>
      <div class="mobile-layout">
        <main class="mobile-canvas-area">
          <CanvasBoard
            ref="canvasBoard"
            :selected-color="selectedColor"
            :is-mobile="true"
            :is-crosshair-mode="isCrosshairMode"
            @draw-enabled="drawEnabled = $event"
            @pixel-placed="() => {}"
            @crosshair-change="crosshairCoord = $event"
          />
        </main>
      </div>

      <FloatingToolbar
        @zoom-in="zoomIn"
        @zoom-out="zoomOut"
        @reset-view="resetCanvasView"
        @toggle-info="toggleInfo"
      />

      <MobileToolbar
        :selected-color="selectedColor"
        :cooldown-seconds="mobileCooldown"
        :is-crosshair-mode="isCrosshairMode"
        :disabled="!drawEnabled"
        :crosshair-coord="crosshairCoord"
        @open-color-picker="openColorPicker"
        @place-pixel="handlePlacePixel"
        @pick-color="handlePickColor"
        @toggle-crosshair="toggleCrosshair"
      />

      <!-- 移动端颜色选择抽屉 -->
      <Transition name="drawer">
        <div v-if="isColorPickerOpen" class="color-drawer" @click.self="closeColorPicker">
          <div class="drawer-content">
            <div class="drawer-header">
              <h3>选择颜色</h3>
              <button class="close-btn" @click="closeColorPicker">✕</button>
            </div>
            <ColorPicker v-model="selectedColor" :show-eyedropper="false" />
          </div>
        </div>
      </Transition>

      <!-- 移动端使用说明抽屉 -->
      <Transition name="drawer">
        <div v-if="isInfoOpen" class="info-drawer" @click.self="toggleInfo">
          <div class="drawer-content">
            <div class="drawer-header">
              <h3>使用说明</h3>
              <button class="close-btn" @click="toggleInfo">✕</button>
            </div>
            <div class="card">
              <ul class="guide-list">
                <li><span class="guide-key">选色</span> 点击底部调色板</li>
                <li><span class="guide-key">绘制</span> 对准准星后点击放置</li>
                <li><span class="guide-key">取色</span> 对准准星后点击底部放大镜</li>
                <li><span class="guide-key">缩放</span> 双指捏合或右侧按钮</li>
                <li><span class="guide-key">移动</span> 单指拖拽画布</li>
                <li><span class="guide-key">协作</span> 与其他用户实时创作</li>
              </ul>
              <div class="tip-box">
                建议开启准星模式，以精确放置或从画布取色。
              </div>
              <div class="tip-box collaboration-tip">
                <strong>共同创作提醒</strong>
                请尊重已有作品，请勿无意义覆盖、涂抹或破坏他人的创作。
              </div>
            </div>
            <div class="card bili-card">
              <div class="bili-link">
                <img src="./assets/bilibili_play.png" alt="Bilibili" class="bili-icon" />
                <a href="https://www.bilibili.com/video/BV1wscrz3ERL" target="_blank" rel="noopener noreferrer">
                  绘画过程可视化
                </a>
              </div>
              <div class="bili-link">
                <img src="./assets/bilibili_play.png" alt="Bilibili" class="bili-icon" />
                <a href="https://space.bilibili.com/259253013" target="_blank" rel="noopener noreferrer">
                  联系站长
                </a>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </template>

    <!-- 覆盖冷却提示弹窗 -->
    <OverwriteCooldownModal :seconds="overwriteCooldown" @close="overwriteCooldown = 0" />
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-body);
}

/* ===== Toast 通知 ===== */
.toast-container {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: var(--radius);
  font-size: 14px;
  font-weight: 500;
  box-shadow: var(--shadow-lg);
  pointer-events: auto;
  white-space: nowrap;
}

.toast-item.warning {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.toast-item.error {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.toast-item.success {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.toast-enter-active {
  transition: all 0.3s ease-out;
}
.toast-leave-active {
  transition: all 0.2s ease-in;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(-12px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ===== 顶部导航 ===== */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  position: sticky;
  top: 0;
  z-index: 100;
}

.app-header.mobile {
  padding: 8px 12px;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  flex-direction: row !important;
  gap: 8px;
}

.app-header.mobile .header-left,
.app-header.mobile .header-right {
  flex: 1 1 auto;
  min-width: 0;
}

.app-header.mobile .header-left {
  flex: 0 0 auto;
}

.app-header.mobile .header-right {
  display: flex;
  justify-content: flex-end;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-img {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  object-fit: contain;
  flex-shrink: 0;
}

.app-header.mobile .logo-img {
  width: 28px;
  height: 28px;
}

.logo-text {
  display: flex;
  flex-direction: column;
}

.title {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.title.mobile {
  font-size: 14px;
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.3;
}

.header-right {
  display: flex;
  align-items: center;
  min-width: 0;
}

.stats-bar {
  display: flex;
  gap: 12px;
}

.app-header.mobile .stats-bar {
  gap: 5px;
}

.stat-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-body);
  border-radius: 20px;
  font-size: 13px;
  white-space: nowrap;
  flex-shrink: 0;
}

.app-header.mobile .stat-chip {
  padding: 2px 6px;
  font-size: 10px;
  gap: 3px;
}

.stat-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.app-header.mobile .stat-dot {
  width: 6px;
  height: 6px;
}

.stat-dot.online {
  background: var(--success);
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.5);
}

.stat-dot.visits {
  background: var(--primary);
}

.stat-dot.pixels {
  background: var(--warning);
}

.stat-num {
  font-weight: 700;
  color: var(--text-primary);
}

.app-header.mobile .stat-num {
  font-size: 10px;
}

.stat-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.app-header.mobile .stat-label {
  font-size: 9px;
}

/* ===== 主体布局 ===== */
.main-container {
  flex: 1;
  display: flex;
  gap: 16px;
  padding: 16px 24px;
  max-width: 1800px;
  margin: 0 auto;
  width: 100%;
}

/* ===== 侧边面板 ===== */
.panel {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ===== 画布区域 ===== */
.canvas-area {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  min-width: 0;
}

/* ===== 卡片通用 ===== */
.card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border-light);
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
}

/* ===== 使用说明 ===== */
.guide-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.guide-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.guide-key {
  display: inline-block;
  min-width: 36px;
  padding: 2px 6px;
  background: var(--primary-light);
  color: var(--primary);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  flex-shrink: 0;
}

.tip-box {
  margin-top: 12px;
  padding: 10px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: #92400e;
  line-height: 1.5;
}

.collaboration-tip {
  margin-top: 10px;
  background: #fff7ed;
  border-color: #fed7aa;
  color: #9a3412;
}

.collaboration-tip strong {
  display: block;
  margin-bottom: 2px;
  font-weight: 700;
}

/* ===== 重置视图按钮 ===== */
.reset-view-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 10px;
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition);
}

.reset-view-btn:hover {
  background: var(--primary-light);
  color: var(--primary);
  border-color: var(--primary);
}

.btn-icon {
  font-size: 16px;
}

/* ===== B站链接 ===== */
.bili-card {
  padding: 12px 16px;
}

.bili-card .bili-link + .bili-link {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light);
}

.bili-link {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bili-icon {
  width: 48px;
  height: 48px;
  object-fit: contain;
  border-radius: var(--radius-sm);
}

.bili-link a {
  color: #00AEEC;
  font-size: 15px;
  font-weight: 600;
  transition: color var(--transition);
}

.bili-link a:hover {
  color: #0083b0;
}

/* ===== 移动端布局 ===== */
.mobile-layout {
  position: fixed;
  top: 50px;
  left: 0;
  right: 0;
  bottom: 76px;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
  background: var(--bg-body);
}

.mobile-canvas-area {
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
}

/* ===== 抽屉 ===== */
.color-drawer,
.info-drawer {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 300;
  display: flex;
  align-items: flex-end;
}

.drawer-content {
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  background: var(--bg-body);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  padding: 16px;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.15);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.drawer-header h3 {
  font-size: 16px;
  font-weight: 600;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-card);
  border-radius: 50%;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.25s ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-active .drawer-content,
.drawer-leave-active .drawer-content {
  transition: transform 0.25s ease;
}

.drawer-enter-from .drawer-content,
.drawer-leave-to .drawer-content {
  transform: translateY(100%);
}

/* ===== 响应式 ===== */
@media (max-width: 1600px) {
  .main-container {
    padding: 12px 16px;
    gap: 12px;
  }
  .panel {
    width: 240px;
  }
}

@media (max-width: 1200px) {
  .app-header:not(.mobile) {
    flex-direction: column;
    gap: 8px;
    padding: 10px 16px;
  }
  .main-container {
    flex-direction: column;
    align-items: center;
  }
  .panel {
    width: 100%;
    max-width: 700px;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .panel > * {
    flex: 1;
    min-width: 200px;
  }
}
</style>

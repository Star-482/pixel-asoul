<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed, inject } from 'vue';
import ws from '../utils/ws.js';

// 画布配置
const props = defineProps({
  width: { type: Number, default: 1000 },
  height: { type: Number, default: 1000 },
  pixelSize: { type: Number, default: 1 },
  selectedColor: { type: String, required: true },
  isMobile: { type: Boolean, default: false },
  isCrosshairMode: { type: Boolean, default: false },
  drawingLocked: { type: Boolean, default: false },
});

const cooldownEventBus = inject('cooldownEventBus')
const isCoolingDown = ref(false);
const drawEnabled = ref(false);
const syncing = ref(true);
const pendingPixels = new Map();
const bufferedEvents = [];
const latestEventByPixel = new Map();
const emit = defineEmits(['pixel-placed', 'crosshair-change', 'draw-enabled']);
const containerRef = ref(null); // 新增：容器引用
// 响应式状态（translate 以"像素"为单位）
const canvasRef = ref(null);
const ctx = ref(null);

const isDragging = ref(false);
const scale = ref(1);               // 缩放比例，>= 1
const translateX = ref(0);          // 平移（px）
const translateY = ref(0);          // 平移（px）
const lastX = ref(0);
const lastY = ref(0);
const dragStartX = ref(0); // 新增：记录拖动开始时的X坐标
const dragStartY = ref(0); // 新增：记录拖动开始时的Y坐标
const dragThreshold = 5; // 拖动阈值，单位为像素
const isDraggingForPlacement = ref(false); // 新增：用于判断是否为放置像素的拖动
const hasDragged = ref(false); // 鼠标按下后是否已越过阈值，进入真正拖动

const dragScaleX = ref(1); // 新增：拖拽时的水平比例修正
const dragScaleY = ref(1); // 新增：拖拽时的垂直比例修正

// 触控状态
const touchStartDist = ref(0);
const touchStartScale = ref(1);
const touchMidpoint = ref({ x: 0, y: 0 });
const isTouchDragging = ref(false);
const touchStartPos = ref({ x: 0, y: 0 });
const lastTapTime = ref(0);
const hasMoved = ref(false);

// 移动端正处于拖拽/缩放时不显示悬停高亮
const isInteracting = ref(false);

// 悬停像素指示
const hoverPixelX = ref(-1);
const hoverPixelY = ref(-1);

// 一些便捷尺寸
const baseCanvasWidth = computed(() => props.width * props.pixelSize);
const baseCanvasHeight = computed(() => props.height * props.pixelSize);

// 容器样式：桌面端固定为画布逻辑尺寸；移动端填满视口以便拖动
const canvasContainerStyle = computed(() => {
  if (props.isMobile) {
    return {
      width: '100%',
      height: '100%',
      backgroundColor: '#fff',
      position: 'relative',
      overflow: 'hidden',
      touchAction: 'none',
    };
  }
  return {
    width: `${baseCanvasWidth.value}px`,
    height: `${baseCanvasHeight.value}px`,
    backgroundColor: '#fff',
    border: '2px solid var(--border, #e2e8f0)',
    borderRadius: 'var(--radius, 10px)',
    boxShadow: '0 4px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.06)',
    display: 'inline-block',
    flexShrink: 0,
    position: 'relative',
    overflow: 'hidden'
  };
});

// 注意：CSS transform 从右到左应用；我们使用 translate(...) scale(...)
// => 实际效果是"先 scale，再 translate（单位为像素）"
const canvasTransformStyle = computed(() => ({
  transform: `translate(${translateX.value}px, ${translateY.value}px) scale(${scale.value})`,
  transformOrigin: '0 0'
}));




// 计算鼠标样式
const canvasCursor = computed(() => {
  return isCoolingDown.value || !drawEnabled.value || props.drawingLocked ? 'not-allowed' : 'pointer';
});

onMounted(async () => {
  const canvas = canvasRef.value;
  if (!canvas) return;

  ctx.value = canvas.getContext('2d');
  ctx.value.imageSmoothingEnabled = false;

  // 物理像素尺寸（绘制坐标系）
  canvas.width = baseCanvasWidth.value;
  canvas.height = baseCanvasHeight.value;


  // 事件
  canvas.addEventListener('click', handleCanvasClick);
  canvas.addEventListener('wheel', handleWheel, { passive: false });
  canvas.addEventListener('mousedown', handleMouseDown);
  canvas.addEventListener('mousemove', handleMouseMove);
  canvas.addEventListener('mouseup', handleMouseUp);
  canvas.addEventListener('mouseleave', handleMouseLeave);

  // 触控事件（移动端）
  canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
  canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
  canvas.addEventListener('touchend', handleTouchEnd, { passive: false });

  // V2 synchronization holds live events until the assigned snapshot and
  // bounded event range have been painted.
  ws.on('session.ready', handleSessionReady);
  ws.on('pixel.updated', handlePixelUpdated);
  ws.on('error', handleServerError);
  ws.on('canvas.reload', handleCanvasReload);
  ws.on('canvas.read_only', handleReadOnlyChanged);

  cooldownEventBus.on(handleCooldownEvent)

  canvas.style.cursor = 'not-allowed';
  clearCanvas();

  // 像素网格覆盖层：容器尺寸变化时重绘，并执行一次初次绘制
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    gridResizeObserver = new ResizeObserver(scheduleDrawGrid);
    gridResizeObserver.observe(containerRef.value);
  }
  scheduleDrawGrid();
});

onBeforeUnmount(() => {
  const canvas = canvasRef.value;
  if (canvas) {
    canvas.removeEventListener('click', handleCanvasClick);
    canvas.removeEventListener('wheel', handleWheel);
    canvas.removeEventListener('mousedown', handleMouseDown);
    canvas.removeEventListener('mousemove', handleMouseMove);
    canvas.removeEventListener('mouseup', handleMouseUp);
    canvas.removeEventListener('mouseleave', handleMouseLeave);
    canvas.removeEventListener('touchstart', handleTouchStart);
    canvas.removeEventListener('touchmove', handleTouchMove);
    canvas.removeEventListener('touchend', handleTouchEnd);
  }
  ws.off('session.ready', handleSessionReady);
  ws.off('pixel.updated', handlePixelUpdated);
  ws.off('error', handleServerError);
  ws.off('canvas.reload', handleCanvasReload);
  ws.off('canvas.read_only', handleReadOnlyChanged);
  cooldownEventBus.off(handleCooldownEvent)
  if (gridResizeObserver) gridResizeObserver.disconnect();
  if (gridRafId) cancelAnimationFrame(gridRafId);
});


// 画布尺寸相关变化时，重设物理像素并重新约束视图
watch(() => [props.pixelSize, props.width, props.height], () => {
  if (!canvasRef.value) return;
  const canvas = canvasRef.value;
  canvas.width = baseCanvasWidth.value;
  canvas.height = baseCanvasHeight.value;
  applyBoundaryConstraints(); // 保证仍不留空白
});




// ============ 缩放（滚轮） ============
function handleWheel(event) {
  event.preventDefault();

  const { x: mx, y: my } = getLocalPosInContainer(event);

  const zoomIntensity = 0.5;
  const factor = event.deltaY < 0 ? (1 + zoomIntensity) : (1 - zoomIntensity);

  let newScale = scale.value * factor;
  newScale = Math.min(40, Math.max(1, newScale));
  if (Math.abs(newScale - 1) < 1e-3) newScale = 1;

  // 以鼠标为锚点：mx = T'x + newScale * cx，其中 cx = (mx - Tx)/scale
  const cx = (mx - translateX.value) / scale.value;
  const cy = (my - translateY.value) / scale.value;

  scale.value = newScale;
  translateX.value = mx - scale.value * cx;
  translateY.value = my - scale.value * cy;

  applyBoundaryConstraints();
}

// ============ 拖拽（像素空间平移） ============
function handleMouseDown(event) {
  isDragging.value = true;
  hasDragged.value = false; // 按下时先进入待判定状态，未越过阈值前不平移
  lastX.value = event.clientX;
  lastY.value = event.clientY;
  dragStartX.value = event.clientX; // 记录拖动开始位置
  dragStartY.value = event.clientY; // 记录拖动开始位置
  isDraggingForPlacement.value = false; // 重置拖动标记

  // === 新增开始：计算拖拽比例（仅桌面端使用）===
  if (!props.isMobile && containerRef.value) {
    const el = containerRef.value;
    const rect = el.getBoundingClientRect();

    // 减去边框影响（与点击逻辑一致）
    const borderLeft = el.clientLeft || 0;
    const borderRight = borderLeft; // 假设对称
    const borderTop = el.clientTop || 0;
    const borderBottom = borderTop; // 假设对称

    const renderedContentWidth = rect.width - borderLeft - borderRight;
    const renderedContentHeight = rect.height - borderTop - borderBottom;

    // 计算比例：逻辑尺寸 / 实际渲染尺寸
    // 例如：逻辑1000 / 渲染500 = 2.0。意味着鼠标动1px，逻辑上要动2px。
    dragScaleX.value = renderedContentWidth > 0 ? baseCanvasWidth.value / renderedContentWidth : 1;
    dragScaleY.value = renderedContentHeight > 0 ? baseCanvasHeight.value / renderedContentHeight : 1;
  }
  // === 新增结束 ===

  if (canvasRef.value && !isCoolingDown.value && drawEnabled.value && !props.drawingLocked) {
    canvasRef.value.style.cursor = 'grabbing';
  }
}

function handleMouseMove(event) {
  // 更新悬停像素位置（无论是否拖拽）
  updateHoverPixel(event);

  if (!isDragging.value) return;

  // 未越过阈值前不平移，避免点击时的细微抖动被当成拖动
  if (!hasDragged.value) {
    const dx = event.clientX - dragStartX.value;
    const dy = event.clientY - dragStartY.value;
    if (dx * dx + dy * dy <= dragThreshold * dragThreshold) return;
    // 越过阈值，正式开始拖动；同步基准点，避免把判定期间的位移一次性补上
    hasDragged.value = true;
    lastX.value = event.clientX;
    lastY.value = event.clientY;
  }

  // 计算物理位移
  const rawDx = event.clientX - lastX.value;
  const rawDy = event.clientY - lastY.value;

  // 桌面端考虑容器与画布逻辑尺寸的比例；移动端容器坐标即屏幕坐标
  if (props.isMobile) {
    translateX.value += rawDx;
    translateY.value += rawDy;
  } else {
    translateX.value += rawDx * dragScaleX.value;
    translateY.value += rawDy * dragScaleY.value;
  }

  lastX.value = event.clientX;
  lastY.value = event.clientY;

  applyBoundaryConstraints();
}

function handleMouseUp() {
  // 越过过阈值才算拖动，抑制点击放置
  if (hasDragged.value) {
    isDraggingForPlacement.value = true;
  }

  isDragging.value = false;
  hasDragged.value = false;
  if (canvasRef.value) {
    canvasRef.value.style.cursor = isCoolingDown.value || !drawEnabled.value || props.drawingLocked ? 'not-allowed' : 'pointer';
  }
}

// 更新悬停像素位置
function updateHoverPixel(event) {
  const { x: mx, y: my } = getLocalPosInContainer(event);
  const canvasX = (mx - translateX.value) / scale.value;
  const canvasY = (my - translateY.value) / scale.value;
  const px = Math.floor(canvasX / props.pixelSize);
  const py = Math.floor(canvasY / props.pixelSize);

  if (px >= 0 && px < props.width && py >= 0 && py < props.height) {
    hoverPixelX.value = px;
    hoverPixelY.value = py;
  } else {
    hoverPixelX.value = -1;
    hoverPixelY.value = -1;
  }
}

// 像素网格：仅在放大到单像素屏幕尺寸 >= 阈值时显示
// 用独立 canvas 覆盖层在屏幕空间画 1 设备像素的硬边线条，并按设备像素取整，
// 与像素化画布的硬边对齐，避免 CSS 渐变抗锯齿在分数缩放/平移下产生的亚像素偏移
const GRID_THRESHOLD = 8; // 单像素在屏幕上 >= 8px 时才画网格
const showGrid = computed(() => props.pixelSize * scale.value >= GRID_THRESHOLD);

const gridCanvasRef = ref(null);
let gridRafId = 0;
let gridResizeObserver = null;

function scheduleDrawGrid() {
  if (gridRafId) return;
  gridRafId = requestAnimationFrame(() => {
    gridRafId = 0;
    drawGrid();
  });
}

function drawGrid() {
  const canvas = gridCanvasRef.value;
  const container = containerRef.value;
  if (!canvas || !container) return;
  const gctx = canvas.getContext('2d');
  if (!gctx) return;

  const dpr = window.devicePixelRatio || 1;
  const cssW = container.clientWidth;
  const cssH = container.clientHeight;
  const bmpW = Math.max(1, Math.floor(cssW * dpr));
  const bmpH = Math.max(1, Math.floor(cssH * dpr));
  // 仅在位图尺寸变化时重设，避免每次重绘都清空
  if (canvas.width !== bmpW || canvas.height !== bmpH) {
    canvas.width = bmpW;
    canvas.height = bmpH;
  }

  gctx.clearRect(0, 0, bmpW, bmpH);
  if (!showGrid.value) return;

  const cell = props.pixelSize * scale.value; // 单像素屏幕尺寸（CSS px）
  const tx = translateX.value;
  const ty = translateY.value;
  gctx.fillStyle = 'rgba(0, 0, 0, 0.12)';

  // 竖线：屏幕 x = tx + k*cell，按设备像素取整对齐像素边缘
  const kMin = Math.ceil(-tx / cell);
  const kMax = Math.floor((cssW - tx) / cell);
  for (let k = kMin; k <= kMax; k++) {
    const x = Math.floor((tx + k * cell) * dpr);
    gctx.fillRect(x, 0, 1, bmpH);
  }
  // 横线
  const jMin = Math.ceil(-ty / cell);
  const jMax = Math.floor((cssH - ty) / cell);
  for (let j = jMin; j <= jMax; j++) {
    const y = Math.floor((ty + j * cell) * dpr);
    gctx.fillRect(0, y, bmpW, 1);
  }
}

watch([scale, translateX, translateY, () => props.pixelSize], scheduleDrawGrid, { flush: 'post' });

// 中央准星（移动端）
const crosshairPixel = computed(() => {
  if (!props.isMobile || !props.isCrosshairMode || !containerRef.value) return null;
  const rect = containerRef.value.getBoundingClientRect();
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;
  const canvasX = (centerX - translateX.value) / scale.value;
  const canvasY = (centerY - translateY.value) / scale.value;
  const x = Math.floor(canvasX / props.pixelSize);
  const y = Math.floor(canvasY / props.pixelSize);

  if (x >= 0 && x < props.width && y >= 0 && y < props.height) {
    return { x, y };
  }
  return null;
});

const crosshairStyle = computed(() => {
  const pos = crosshairPixel.value;
  if (!pos) return null;
  const ps = props.pixelSize;
  const s = scale.value;
  const size = Math.max(ps * s, 12); // 最小 12px，保证可见
  const tx = translateX.value + pos.x * ps * s + (ps * s - size) / 2;
  const ty = translateY.value + pos.y * ps * s + (ps * s - size) / 2;
  return {
    transform: `translate(${tx}px, ${ty}px)`,
    width: `${size}px`,
    height: `${size}px`,
  };
});

// 准星坐标变化时通知父组件
watch(crosshairPixel, (newVal, oldVal) => {
  if (
    !oldVal ||
    !newVal ||
    oldVal.x !== newVal.x ||
    oldVal.y !== newVal.y
  ) {
    emit('crosshair-change', newVal);
  }
}, { immediate: true });

function handleMouseLeave() {
  handleMouseUp();
  hoverPixelX.value = -1;
  hoverPixelY.value = -1;
}

// ============ 触控操作 ============
function getTouchDistance(touches) {
  const dx = touches[0].clientX - touches[1].clientX;
  const dy = touches[0].clientY - touches[1].clientY;
  return Math.sqrt(dx * dx + dy * dy);
}

function getTouchMidpoint(touches) {
  return {
    x: (touches[0].clientX + touches[1].clientX) / 2,
    y: (touches[0].clientY + touches[1].clientY) / 2,
  };
}

function getLocalPosFromTouch(touch) {
  return getLocalPosInContainer({ clientX: touch.clientX, clientY: touch.clientY });
}

function handleTouchStart(event) {
  if (event.touches.length === 1) {
    const touch = event.touches[0];
    isTouchDragging.value = true;
    hasMoved.value = false;
    touchStartPos.value = { x: touch.clientX, y: touch.clientY };
    lastX.value = touch.clientX;
    lastY.value = touch.clientY;
    isInteracting.value = true;
  } else if (event.touches.length === 2) {
    isTouchDragging.value = false;
    touchStartDist.value = getTouchDistance(event.touches);
    touchStartScale.value = scale.value;
    touchMidpoint.value = getTouchMidpoint(event.touches);
    isInteracting.value = true;
  }
}

function handleTouchMove(event) {
  event.preventDefault();

  if (event.touches.length === 1 && isTouchDragging.value) {
    const touch = event.touches[0];
    const dx = touch.clientX - lastX.value;
    const dy = touch.clientY - lastY.value;

    translateX.value += dx;
    translateY.value += dy;

    lastX.value = touch.clientX;
    lastY.value = touch.clientY;

    if (Math.abs(touch.clientX - touchStartPos.value.x) > dragThreshold ||
        Math.abs(touch.clientY - touchStartPos.value.y) > dragThreshold) {
      hasMoved.value = true;
    }

    applyBoundaryConstraints();
  } else if (event.touches.length === 2) {
    const newDist = getTouchDistance(event.touches);
    if (touchStartDist.value > 0) {
      let newScale = touchStartScale.value * (newDist / touchStartDist.value);
      newScale = Math.min(40, Math.max(1, newScale));

      // 以双指中点为锚点缩放
      const localMid = getLocalPosInContainer({
        clientX: touchMidpoint.value.x,
        clientY: touchMidpoint.value.y,
      });
      const cx = (localMid.x - translateX.value) / scale.value;
      const cy = (localMid.y - translateY.value) / scale.value;

      scale.value = newScale;
      translateX.value = localMid.x - scale.value * cx;
      translateY.value = localMid.y - scale.value * cy;
      applyBoundaryConstraints();
    }
  }
}

function handleTouchEnd(event) {
  if (event.touches.length === 0) {
    // 所有手指离开
    if (isTouchDragging.value && !hasMoved.value && props.isMobile && !isCoolingDown.value) {
      // 移动端轻点画布直接放置像素（无论是否开启准星模式）
      const touch = event.changedTouches[0];
      placeAtPoint(touch.clientX, touch.clientY);
    }
    isTouchDragging.value = false;
    isInteracting.value = false;
  } else if (event.touches.length === 1) {
    // 从双指变单指，继续拖拽
    isTouchDragging.value = true;
    hasMoved.value = true;
    const touch = event.touches[0];
    lastX.value = touch.clientX;
    lastY.value = touch.clientY;
    touchStartPos.value = { x: touch.clientX, y: touch.clientY };
  }
}

// ============ 像素放置 ============
function placeAtPoint(clientX, clientY) {
  if (isCoolingDown.value || !drawEnabled.value || props.drawingLocked || syncing.value) return;
  if (!containerRef.value) return;

  const { x: mx, y: my } = getLocalPosInContainer({ clientX, clientY });
  const canvasX = (mx - translateX.value) / scale.value;
  const canvasY = (my - translateY.value) / scale.value;
  const x = Math.floor(canvasX / props.pixelSize);
  const y = Math.floor(canvasY / props.pixelSize);

  if (x >= 0 && x < props.width && y >= 0 && y < props.height) {
    placePixel(x, y);
  }
}

function getCrosshairPixel() {
  if (!containerRef.value) return null;
  const rect = containerRef.value.getBoundingClientRect();
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;
  const canvasX = (centerX - translateX.value) / scale.value;
  const canvasY = (centerY - translateY.value) / scale.value;
  const x = Math.floor(canvasX / props.pixelSize);
  const y = Math.floor(canvasY / props.pixelSize);

  if (x >= 0 && x < props.width && y >= 0 && y < props.height) {
    return { x, y };
  }
  return null;
}

function placeAtCrosshair() {
  if (isCoolingDown.value || !drawEnabled.value || props.drawingLocked || syncing.value) return false;
  const pos = getCrosshairPixel();
  if (!pos) return false;
  return placePixel(pos.x, pos.y);
}

function pickAtCrosshair() {
  if (syncing.value) return null;
  const pos = getCrosshairPixel();
  if (!pos) return null;
  return { ...pos, color: readPixel(pos.x, pos.y) };
}

function zoomIn() {
  zoomBy(2);
}

function zoomOut() {
  zoomBy(0.5);
}

function zoomBy(factor) {
  if (!containerRef.value) return;
  const rect = containerRef.value.getBoundingClientRect();
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;
  const localCenter = { x: centerX, y: centerY };

  let newScale = scale.value * factor;
  newScale = Math.min(40, Math.max(1, newScale));

  const cx = (localCenter.x - translateX.value) / scale.value;
  const cy = (localCenter.y - translateY.value) / scale.value;

  scale.value = newScale;
  translateX.value = localCenter.x - scale.value * cx;
  translateY.value = localCenter.y - scale.value * cy;
  applyBoundaryConstraints();
}

function handleCanvasClick(event) {
  // 移动端由 touch 事件或底部"放置"按钮处理，不响应鼠标点击
  if (props.isMobile) return;

  // 如果是拖动浏览，则不执行像素放置
  if (isDraggingForPlacement.value) {
    isDraggingForPlacement.value = false; // 重置标记
    return;
  }

  // 如果在冷却中，则不执行像素放置
  if (isCoolingDown.value || !drawEnabled.value || props.drawingLocked || syncing.value) return;

  placeAtPoint(event.clientX, event.clientY);
}

function drawPixel(x, y, color) {
  if (!ctx.value) return;
  ctx.value.fillStyle = color;
  ctx.value.fillRect(
    x * props.pixelSize,
    y * props.pixelSize,
    props.pixelSize,
    props.pixelSize
  );
}

// ============ V2 initialization and optimistic pixels ============
async function handleSessionReady(message) {
  const ready = message.data;
  syncing.value = true;
  drawEnabled.value = Boolean(ready.draw_enabled);
  emit('draw-enabled', drawEnabled.value);
  bufferedEvents.length = 0;
  latestEventByPixel.clear();
  clearCanvas();

  try {
    let cursor = 0;
    if (ready.snapshot) {
      await drawPNGImage(ready.snapshot.url);
      cursor = ready.snapshot.last_event_id;
    }
    while (cursor < ready.head_event_id) {
      const response = await fetch(`/api/v2/canvas/events?after=${cursor}&through=${ready.head_event_id}&limit=5000`, { credentials: 'same-origin' });
      if (!response.ok) throw new Error('无法获取画布增量');
      const page = await response.json();
      (page.events || []).forEach(applyConfirmedEvent);
      if (!page.events?.length) break;
      cursor = page.events[page.events.length - 1].event_id;
    }
    bufferedEvents
      .filter(event => event.event_id > ready.head_event_id)
      .sort((a, b) => a.event_id - b.event_id)
      .forEach(applyConfirmedEvent);
  } catch (error) {
    console.error('画布 V2 同步失败', error);
    drawEnabled.value = false;
    emit('draw-enabled', false);
  } finally {
    bufferedEvents.length = 0;
    // A closed socket does not blindly replay a placement. Keep the original
    // request IDs visible so an explicit retry can stay idempotent after sync.
    for (const pending of pendingPixels.values()) drawPixel(pending.x, pending.y, pending.color);
    syncing.value = false;
  }
}

function handlePixelUpdated(message) {
  const event = message.data;
  if (syncing.value) {
    bufferedEvents.push(event);
    return;
  }
  applyConfirmedEvent(event);
}

function applyConfirmedEvent(event) {
  const key = `${event.x}:${event.y}`;
  if ((latestEventByPixel.get(key) || 0) >= event.event_id) return;
  latestEventByPixel.set(key, event.event_id);
  drawPixel(event.x, event.y, event.color);
  for (const [requestId, pending] of pendingPixels) {
    if (pending.x === event.x && pending.y === event.y) pendingPixels.delete(requestId);
  }
}

function handleServerError(message) {
  const error = message.data || {};
  if (message.request_id && pendingPixels.has(message.request_id)) {
    const pending = pendingPixels.get(message.request_id);
    pendingPixels.delete(message.request_id);
    drawPixel(pending.x, pending.y, pending.previousColor);
  }
  if (error.code === 'canvas_read_only') {
    drawEnabled.value = false;
    emit('draw-enabled', false);
  }
  // `destructive_cooldown` only blocks overwriting non-white pixels. Keep
  // this canvas interactive so the user can continue drawing on blank areas;
  // the server remains the authority for every individual placement.
  const blocksAllDrawing = error.code === 'rate_limited' || error.code === 'drawing_blocked';
  if (blocksAllDrawing && error.retry_after) {
    isCoolingDown.value = true;
    window.setTimeout(() => { isCoolingDown.value = false; }, error.retry_after * 1000);
  }
}

function handleCanvasReload() {
  ws.close();
  const url = window.location.protocol === 'https:' ? `wss://${window.location.host}/ws/canvas` : `ws://${window.location.host}/ws/canvas`;
  ws.connect(url);
}

function handleReadOnlyChanged(message) {
  drawEnabled.value = Boolean(message.data?.draw_enabled);
  emit('draw-enabled', drawEnabled.value);
}

function placePixel(x, y) {
  const requestId = crypto.randomUUID();
  const previousColor = readPixel(x, y);
  if (!ws.send('pixel.place', { x, y, color: props.selectedColor }, requestId)) return false;
  pendingPixels.set(requestId, { x, y, previousColor, color: props.selectedColor });
  drawPixel(x, y, props.selectedColor);
  emit('pixel-placed');
  return true;
}

function readPixel(x, y) {
  if (!ctx.value) return '#FFFFFF';
  const rgb = ctx.value.getImageData(x * props.pixelSize, y * props.pixelSize, 1, 1).data;
  return `#${[rgb[0], rgb[1], rgb[2]].map(value => value.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

function clearCanvas() {
  if (!ctx.value) return;
  ctx.value.fillStyle = '#FFFFFF';
  ctx.value.fillRect(0, 0, baseCanvasWidth.value, baseCanvasHeight.value);
}

function drawPNGImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (ctx.value) {
        ctx.value.imageSmoothingEnabled = false;
        ctx.value.drawImage(image, 0, 0, baseCanvasWidth.value, baseCanvasHeight.value);
      }
      resolve();
    };
    image.onerror = () => reject(new Error('无法加载快照'));
    image.src = url;
  });
}

// ============ 边界约束（像素空间） ============
// 规则：不留空白。桌面端容器大小等于画布基准大小；移动端容器为视口大小。
// translateX ∈ [Cw - Sw, 0]，translateY ∈ [Ch - Sh, 0]
function applyBoundaryConstraints() {
  const el = containerRef.value;
  // 移动端以容器可见尺寸为边界；桌面端以画布基准尺寸为边界
  const Cw = el && props.isMobile ? el.clientWidth : baseCanvasWidth.value;
  const Ch = el && props.isMobile ? el.clientHeight : baseCanvasHeight.value;
  const Sw = baseCanvasWidth.value * scale.value;
  const Sh = baseCanvasHeight.value * scale.value;

  const minTx = Math.min(0, Cw - Sw);
  const maxTx = 0;
  translateX.value = Math.min(maxTx, Math.max(minTx, translateX.value));

  const minTy = Math.min(0, Ch - Sh);
  const maxTy = 0;
  translateY.value = Math.min(maxTy, Math.max(minTy, translateY.value));
}

// 重置视图
function resetView() {
  scale.value = 1;
  translateX.value = 0;
  translateY.value = 0;
  applyBoundaryConstraints();
}

// 获取鼠标位置
function getLocalPosInContainer(event) {
  const el = containerRef.value;
  if (!el) return { x: 0, y: 0 };

  const rect = el.getBoundingClientRect();

  // 获取边框宽度（clientLeft 通常等于左边框宽度）
  const borderLeft = el.clientLeft || 0;
  const borderTop = el.clientTop || 0;

  // 计算在容器内容区中的坐标
  let x = event.clientX - rect.left - borderLeft;
  let y = event.clientY - rect.top - borderTop;

  if (!props.isMobile) {
    // 桌面端：容器尺寸与画布逻辑尺寸一致，此比例为 1
    // 保留原有逻辑以兼容可能的 CSS 缩放场景
    const borderRight = borderLeft;
    const borderBottom = borderTop;
    const renderedContentWidth = rect.width - borderLeft - borderRight;
    const renderedContentHeight = rect.height - borderTop - borderBottom;
    const scaleX = renderedContentWidth > 0 ? baseCanvasWidth.value / renderedContentWidth : 1;
    const scaleY = renderedContentHeight > 0 ? baseCanvasHeight.value / renderedContentHeight : 1;
    x *= scaleX;
    y *= scaleY;
  }

  return { x, y };
}

function handleCooldownEvent(event) { 
  if (event.type === 'cooldown-end') {
    // 处理冷却结束逻辑
    isCoolingDown.value = false
    // console.log('冷却结束')
    // 立即更新游标样式
    if (canvasRef.value) {
      canvasRef.value.style.cursor = drawEnabled.value && !props.drawingLocked ? 'pointer' : 'not-allowed';
    }
  }
}

// 暴露方法
defineExpose({
  resetView,
  zoomIn,
  zoomOut,
  placeAtCrosshair,
  pickAtCrosshair,
  getCrosshairPixel,
});
</script>


<template>
  <div
    :style="canvasContainerStyle"
    ref="containerRef"
    class="canvas-container"
  >
    <canvas
      ref="canvasRef"
      class="pixel-canvas"
      :style="{ ...canvasTransformStyle, cursor: canvasCursor }"
    ></canvas>
    <canvas
      ref="gridCanvasRef"
      class="pixel-grid-canvas"
    ></canvas>
    <div
      v-if="crosshairStyle"
      class="crosshair"
      :style="crosshairStyle"
    >
      <div class="crosshair-h"></div>
      <div class="crosshair-v"></div>
    </div>
    <div v-if="hoverPixelX >= 0 && hoverPixelY >= 0 && !isInteracting" class="coord-badge">
      ({{ hoverPixelX }}, {{ hoverPixelY }})
    </div>
  </div>
</template>


<style scoped>
.pixel-canvas {
  display: block;
  image-rendering: pixelated;
  image-rendering: -moz-crisp-edges;
  image-rendering: crisp-edges;
  transform-origin: 0 0;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
  -webkit-user-select: none;
}

.canvas-container {
  -webkit-tap-highlight-color: transparent;
  user-select: none;
  -webkit-user-select: none;
}

.pixel-grid-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: block;
  pointer-events: none;
  z-index: 2;
}

.crosshair {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 5;
}

.crosshair-h,
.crosshair-v {
  position: absolute;
  background: rgba(239, 68, 68, 0.9);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8);
}

.crosshair-h {
  top: 50%;
  left: 0;
  width: 100%;
  height: 2px;
  transform: translateY(-50%);
}

.crosshair-v {
  left: 50%;
  top: 0;
  width: 2px;
  height: 100%;
  transform: translateX(-50%);
}
</style>

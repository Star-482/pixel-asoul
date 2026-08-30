<script setup>
import { computed, reactive, ref, watch } from 'vue';

const props = defineProps({
  canvas: { type: Object, required: true },
  preview: { type: Object, default: null },
  plan: { type: Object, default: null },
  operation: { type: Object, default: null },
  selectedTime: { type: String, default: '' },
  busy: { type: Boolean, default: false },
});

const emit = defineEmits(['create-preview', 'create-plan', 'execute-plan']);
const image = ref(null);
const dragging = ref(false);
const dragStart = ref(null);
const confirmationText = ref('');
const showDifference = ref(true);
const form = reactive({
  target_event_id: '', target_time: '', mode: 'selective', event_to_id: '',
  visitor_id: '', connection_id: '', x_min: 0, y_min: 0, x_max: 999, y_max: 999,
});

watch(() => [props.canvas?.width, props.canvas?.height], ([width, height]) => {
  if (!width || !height) return;
  const dimensionsChanged = Number(form.x_max) >= width || Number(form.y_max) >= height;
  if (dimensionsChanged || (Number(form.x_max) === 999 && Number(form.y_max) === 999)) {
    form.x_max = width - 1;
    form.y_max = height - 1;
  }
  if (!form.event_to_id) form.event_to_id = props.canvas.head_event_id;
}, { immediate: true });

watch(() => props.selectedTime, time => {
  if (!time) return;
  form.target_time = toLocalInput(time);
  form.target_event_id = '';
});

watch(() => props.preview, preview => {
  if (preview?.target_event_id !== undefined) form.target_event_id = preview.target_event_id;
}, { deep: true });

const fullCanvas = computed(() => (
  form.mode === 'exact'
  && Number(form.x_min) === 0 && Number(form.y_min) === 0
  && Number(form.x_max) === props.canvas.width - 1 && Number(form.y_max) === props.canvas.height - 1
));

const selectionStyle = computed(() => {
  if (!props.canvas?.width || !props.canvas?.height) return {};
  const left = (Number(form.x_min) / props.canvas.width) * 100;
  const top = (Number(form.y_min) / props.canvas.height) * 100;
  const width = ((Number(form.x_max) - Number(form.x_min) + 1) / props.canvas.width) * 100;
  const height = ((Number(form.y_max) - Number(form.y_min) + 1) / props.canvas.height) * 100;
  return { left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%` };
});

function previewPayload() {
  if (form.target_event_id !== '' && form.target_event_id !== null) return { target_event_id: Number(form.target_event_id) };
  if (form.target_time) return { target_time: new Date(form.target_time).toISOString() };
  return null;
}

function createPreview() {
  const payload = previewPayload();
  if (payload) emit('create-preview', payload);
}

function createPlan() {
  if (form.target_event_id === '' || form.target_event_id === null) return;
  emit('create-plan', {
    mode: form.mode,
    target_event_id: Number(form.target_event_id),
    filters: {
      x_min: Number(form.x_min), x_max: Number(form.x_max), y_min: Number(form.y_min), y_max: Number(form.y_max),
      event_to_id: Number(form.event_to_id || props.canvas.head_event_id),
      visitor_id: form.visitor_id.trim() || undefined,
      connection_id: form.connection_id.trim() || undefined,
    },
  });
}

function executePlan() {
  emit('execute-plan', { confirmation_text: confirmationText.value });
}

function pointFromEvent(event) {
  const rect = image.value?.getBoundingClientRect();
  if (!rect) return null;
  return {
    x: Math.min(props.canvas.width - 1, Math.max(0, Math.floor(((event.clientX - rect.left) / rect.width) * props.canvas.width))),
    y: Math.min(props.canvas.height - 1, Math.max(0, Math.floor(((event.clientY - rect.top) / rect.height) * props.canvas.height))),
  };
}

function beginSelection(event) {
  const point = pointFromEvent(event);
  if (!point) return;
  dragging.value = true;
  dragStart.value = point;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  updateSelection(point);
}

function moveSelection(event) {
  if (!dragging.value) return;
  const point = pointFromEvent(event);
  if (point) updateSelection(point);
}

function endSelection(event) {
  if (!dragging.value) return;
  const point = pointFromEvent(event);
  if (point) updateSelection(point);
  dragging.value = false;
  dragStart.value = null;
}

function updateSelection(point) {
  const start = dragStart.value || point;
  form.x_min = Math.min(start.x, point.x);
  form.x_max = Math.max(start.x, point.x);
  form.y_min = Math.min(start.y, point.y);
  form.y_max = Math.max(start.y, point.y);
}

function setTargetTime(time) {
  form.target_time = toLocalInput(time);
  form.target_event_id = '';
  createPreview();
}

function toLocalInput(value) {
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

defineExpose({ setTargetTime });
</script>

<template>
  <section class="card restore-card">
    <div class="section-heading"><div><h2>历史预览与恢复</h2><p>先查看历史状态，再框选区域并生成十分钟有效的恢复计划。</p></div><span v-if="busy" class="loading">处理中…</span></div>
    <div class="target-row">
      <label>目标事件 <input v-model.number="form.target_event_id" type="number" min="0" @input="form.target_time = ''" /></label>
      <label>目标时间 <input v-model="form.target_time" type="datetime-local" @input="form.target_event_id = ''" /></label>
      <button @click="createPreview">生成历史预览</button>
    </div>

    <div v-if="preview" class="preview-summary">
      <span>事件 {{ preview.target_event_id }} / 当前 {{ preview.head_event_id }}</span>
      <strong>与当前画布相差 {{ preview.difference_pixels.toLocaleString() }} 像素</strong>
      <label v-if="preview.difference_url" class="difference-toggle"><input v-model="showDifference" type="checkbox" /> 高亮差异</label>
      <span>预览十分钟后失效</span>
    </div>
    <div v-if="preview" class="preview-stage" @pointerdown="beginSelection" @pointermove="moveSelection" @pointerup="endSelection" @pointercancel="endSelection">
      <img ref="image" :src="preview.url" alt="历史画布预览；拖动以选择恢复区域" draggable="false" />
      <img v-if="showDifference && preview.difference_url" class="difference-overlay" :src="preview.difference_url" alt="红色区域表示与当前画布不同的像素" draggable="false" />
      <div class="selection" :style="selectionStyle"></div>
    </div>
    <p v-else class="empty-preview">选择时间点后生成预览；在预览图上拖动即可框选恢复区域。</p>

    <div class="form-grid">
      <label>恢复模式 <select v-model="form.mode"><option value="selective">撤销可疑事件</option><option value="exact">精确恢复区域</option></select></label>
      <label v-if="form.mode === 'selective'">撤销至事件 <input v-model.number="form.event_to_id" type="number" min="0" :max="canvas.head_event_id" /></label>
      <label>访客 ID（可选）<input v-model.trim="form.visitor_id" placeholder="UUID" /></label>
      <label>连接 ID（可选）<input v-model.trim="form.connection_id" placeholder="UUID" /></label>
      <label>X 起点 <input v-model.number="form.x_min" type="number" :min="0" :max="canvas.width - 1" /></label>
      <label>Y 起点 <input v-model.number="form.y_min" type="number" :min="0" :max="canvas.height - 1" /></label>
      <label>X 终点 <input v-model.number="form.x_max" type="number" :min="0" :max="canvas.width - 1" /></label>
      <label>Y 终点 <input v-model.number="form.y_max" type="number" :min="0" :max="canvas.height - 1" /></label>
    </div>
    <p v-if="form.mode === 'selective'" class="help">选择性撤销只会恢复“当前最后一次修改仍属于筛选事件”的坐标；后续正常修改会自动跳过。</p>
    <p v-else class="help warning">精确恢复会将所选区域还原至目标事件的状态，可能覆盖后续修改。</p>
    <button :disabled="busy || form.target_event_id === ''" @click="createPlan">创建恢复计划</button>

    <div v-if="plan" class="plan-box">
      <strong>恢复计划已生成：{{ plan.affected_pixels.toLocaleString() }} 个像素</strong>
      <span>计划会在 {{ new Date(plan.expires_at).toLocaleTimeString('zh-CN') }} 失效；画布变化后须重新生成。</span>
      <span v-if="form.mode === 'exact'">此恢复将覆盖 {{ (plan.subsequent_changes ?? 0).toLocaleString() }} 条目标事件后的修改。</span>
      <label v-if="fullCanvas">整图精确恢复确认 <input v-model="confirmationText" placeholder="请输入：恢复整图" /></label>
      <button class="danger" :disabled="busy" @click="executePlan">执行恢复</button>
    </div>
    <div v-if="operation && (operation.status === 'queued' || operation.status === 'running')" class="operation-box">
      <strong>大范围恢复{{ operation.status === 'queued' ? '已排队' : '执行中' }}</strong>
      <span>操作 {{ operation.id }}。画布暂时只读，页面会自动刷新执行状态。</span>
    </div>
  </section>
</template>

<style scoped>
.card { background: #fff; border: 1px solid #dbe3ee; border-radius: 14px; padding: 22px; box-shadow: 0 4px 16px #1720330d; }.section-heading { display:flex; justify-content:space-between; gap:16px; }.section-heading h2 { margin:0; font-size:20px; }.section-heading p,.help,.empty-preview { color:#64748b; font-size:13px; line-height:1.55; }.loading { color:#2563eb; font-size:13px; }.target-row,.form-grid { display:grid; gap:10px; margin-top:16px; }.target-row { grid-template-columns:repeat(3,minmax(0,1fr)); align-items:end; }.form-grid { grid-template-columns:repeat(4,minmax(0,1fr)); }.target-row label,.form-grid label,.plan-box label { display:grid; gap:5px; color:#475569; font-size:12px; }input,select,button { font:inherit; box-sizing:border-box; min-width:0; }input,select { padding:8px; border:1px solid #cbd5e1; border-radius:7px; }button { background:#2563eb; color:#fff; border:1px solid #2563eb; border-radius:7px; padding:9px 12px; cursor:pointer; }button:disabled { opacity:.55; cursor:not-allowed; }.preview-summary { display:flex; flex-wrap:wrap; gap:12px; margin-top:16px; padding:9px 11px; background:#eff6ff; border-radius:8px; color:#1e3a8a; font-size:12px; }.difference-toggle { display:flex; gap:5px; align-items:center; cursor:pointer; }.difference-toggle input { padding:0; }.preview-stage { position:relative; width:min(100%,700px); margin:14px 0; border:1px solid #cbd5e1; line-height:0; touch-action:none; cursor:crosshair; }.preview-stage img { display:block; width:100%; image-rendering:pixelated; user-select:none; }.preview-stage .difference-overlay { position:absolute; inset:0; opacity:.52; mix-blend-mode:multiply; pointer-events:none; }.selection { position:absolute; border:2px solid #ef4444; background:#ef444424; pointer-events:none; box-sizing:border-box; }.warning { color:#b45309; }.plan-box,.operation-box { display:grid; gap:10px; margin-top:16px; padding:14px; border:1px solid #fdba74; background:#fff7ed; border-radius:9px; color:#9a3412; }.plan-box span,.operation-box span { font-size:12px; }.operation-box { border-color:#93c5fd; background:#eff6ff; color:#1e3a8a; }.danger { background:#b91c1c; border-color:#b91c1c; width:max-content; }.help { margin:10px 0; }
@media (max-width:850px) { .target-row,.form-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } } @media (max-width:520px) { .card { padding:16px; }.target-row,.form-grid { grid-template-columns:1fr; } }
</style>

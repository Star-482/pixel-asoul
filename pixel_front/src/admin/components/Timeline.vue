<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
  buckets: { type: Array, default: () => [] },
  snapshots: { type: Array, default: () => [] },
  start: { type: String, required: true },
  end: { type: String, required: true },
  selectedTime: { type: String, default: '' },
  loading: { type: Boolean, default: false },
});

const emit = defineEmits(['change-range', 'select-time']);
const startInput = ref('');
const endInput = ref('');
const position = ref(100);
const playing = ref(false);
let playbackTimer = null;

function toInput(value) {
  if (!value) return '';
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function toIso(value) {
  return value ? new Date(value).toISOString() : '';
}

watch(() => [props.start, props.end], ([start, end]) => {
  startInput.value = toInput(start);
  endInput.value = toInput(end);
}, { immediate: true });

const maxCount = computed(() => Math.max(1, ...props.buckets.map(bucket => Number(bucket.count) || 0)));
const startMs = computed(() => new Date(props.start).getTime());
const endMs = computed(() => new Date(props.end).getTime());

function formatTime(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value));
}

function emitRange() {
  const start = toIso(startInput.value);
  const end = toIso(endInput.value);
  if (!start || !end || new Date(start) > new Date(end)) return;
  emit('change-range', { start, end });
}

function selectAtRatio(rawRatio) {
  const ratio = Math.min(1, Math.max(0, Number(rawRatio)));
  position.value = Math.round(ratio * 1000) / 10;
  const time = new Date(startMs.value + (endMs.value - startMs.value) * ratio).toISOString();
  emit('select-time', time);
}

function selectBucket(bucket) {
  emit('select-time', bucket.time);
  const span = Math.max(1, endMs.value - startMs.value);
  position.value = Math.round(((new Date(bucket.time).getTime() - startMs.value) / span) * 1000) / 10;
}

function shift(minutes) {
  const selected = props.selectedTime ? new Date(props.selectedTime).getTime() : endMs.value;
  const time = Math.min(endMs.value, Math.max(startMs.value, selected + minutes * 60 * 1000));
  selectAtRatio((time - startMs.value) / Math.max(1, endMs.value - startMs.value));
}

function togglePlayback() {
  playing.value = !playing.value;
  if (!playing.value) {
    clearInterval(playbackTimer);
    playbackTimer = null;
    return;
  }
  playbackTimer = setInterval(() => {
    const next = position.value >= 100 ? 0 : Math.min(100, position.value + 1);
    selectAtRatio(next / 100);
  }, 800);
}

function markerStyle(snapshot) {
  const span = Math.max(1, endMs.value - startMs.value);
  const left = ((new Date(snapshot.created_at).getTime() - startMs.value) / span) * 100;
  return { left: `${Math.min(100, Math.max(0, left))}%` };
}

onBeforeUnmount(() => clearInterval(playbackTimer));
</script>

<template>
  <section class="card timeline-card">
    <div class="section-heading">
      <div>
        <h2>时间轴</h2>
        <p>所有时间按 Asia/Shanghai 显示；拖动滑块会生成对应历史预览。</p>
      </div>
      <span v-if="loading" class="loading">加载中…</span>
    </div>

    <div class="range-controls">
      <label>开始 <input v-model="startInput" type="datetime-local" @change="emitRange" /></label>
      <label>结束 <input v-model="endInput" type="datetime-local" @change="emitRange" /></label>
      <button class="secondary" @click="emitRange">刷新区间</button>
    </div>

    <div class="timeline-shell">
      <div class="timeline-bars" aria-label="修改密度时间轴">
        <button
          v-for="bucket in buckets"
          :key="bucket.time"
          class="timeline-bar"
          :title="`${formatTime(bucket.time)}：${bucket.count} 次修改`"
          :style="{ height: `${Math.max(3, (Number(bucket.count) / maxCount) * 100)}%` }"
          @click="selectBucket(bucket)"
        ></button>
        <button
          v-for="snapshot in snapshots"
          :key="snapshot.id"
          class="snapshot-marker"
          :style="markerStyle(snapshot)"
          :title="`快照 #${snapshot.id} · 事件 ${snapshot.event_id}`"
          @click="emit('select-time', snapshot.created_at)"
        >◆</button>
      </div>
      <div class="timeline-labels"><span>{{ formatTime(start) }}</span><span>{{ formatTime(end) }}</span></div>
    </div>

    <div class="scrubber-row">
      <button class="icon-button" title="后退五分钟" @click="shift(-5)">‹</button>
      <input v-model.number="position" type="range" min="0" max="100" step="0.1" @input="selectAtRatio(position / 100)" />
      <button class="icon-button" title="前进五分钟" @click="shift(5)">›</button>
      <button class="secondary" @click="togglePlayback">{{ playing ? '暂停' : '播放' }}</button>
      <output>{{ selectedTime ? formatTime(selectedTime) : '选择时间点' }}</output>
    </div>
  </section>
</template>

<style scoped>
.card { background: #fff; border: 1px solid #dbe3ee; border-radius: 14px; padding: 22px; box-shadow: 0 4px 16px #1720330d; }
.section-heading { display: flex; justify-content: space-between; gap: 16px; align-items: start; }.section-heading h2 { margin: 0; font-size: 20px; }.section-heading p { margin: 6px 0 0; color: #64748b; font-size: 13px; }.loading { color: #2563eb; font-size: 13px; }
.range-controls,.scrubber-row { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; margin-top: 18px; }.range-controls label { display: grid; gap: 5px; color: #475569; font-size: 12px; }.range-controls input { min-width: 185px; }
input,button { font: inherit; }.secondary,.icon-button { background: #fff; color: #1e40af; border: 1px solid #bfdbfe; border-radius: 7px; padding: 8px 10px; cursor: pointer; }.icon-button { font-size: 20px; line-height: 18px; min-width: 34px; }
.timeline-shell { margin-top: 18px; }.timeline-bars { position: relative; height: 152px; display: flex; align-items: end; gap: 2px; border: 1px solid #dbe3ee; border-radius: 9px 9px 0 0; overflow: hidden; padding: 10px 8px 0; background: linear-gradient(to bottom, #f8fbff, #fff); }.timeline-bar { min-width: 3px; flex: 1; border: 0; background: linear-gradient(#60a5fa, #2563eb); cursor: pointer; border-radius: 2px 2px 0 0; }.timeline-bar:hover { background: #1d4ed8; }.snapshot-marker { position: absolute; bottom: 2px; transform: translateX(-50%); color: #b45309; border: 0; background: transparent; cursor: pointer; font-size: 13px; padding: 0; }.timeline-labels { display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-top: 5px; }.scrubber-row input { flex: 1; min-width: 200px; accent-color: #2563eb; } output { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #334155; }
@media (max-width: 640px) { .card { padding: 16px; }.range-controls label,.range-controls input { width: 100%; }.timeline-bars { height: 115px; } }
</style>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { parseApiInstant, shanghaiDatetimeLocalToIso, toShanghaiDatetimeLocal } from '../time';

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
  return toShanghaiDatetimeLocal(value);
}

function toIso(value) {
  return shanghaiDatetimeLocalToIso(value);
}

watch(() => [props.start, props.end], ([start, end]) => {
  startInput.value = toInput(start);
  endInput.value = toInput(end);
}, { immediate: true });

const maxCount = computed(() => Math.max(1, ...props.buckets.map(bucket => Number(bucket.count) || 0)));
const startMs = computed(() => parseApiInstant(props.start).getTime());
const endMs = computed(() => parseApiInstant(props.end).getTime());
const timeSpan = computed(() => Math.max(1, endMs.value - startMs.value));

function timeRatio(time) {
  return Math.min(1, Math.max(0, (time - startMs.value) / timeSpan.value));
}

watch(() => props.selectedTime, time => {
  if (!time) return;
  position.value = Math.round(timeRatio(parseApiInstant(time).getTime()) * 1000) / 10;
});

const snapshotMarkers = computed(() => {
  const lanes = new Map();
  return [...props.snapshots]
    .map(snapshot => ({ ...snapshot, timeline_time: snapshot.event_time || snapshot.created_at }))
    .filter(snapshot => Number.isFinite(parseApiInstant(snapshot.timeline_time).getTime()))
    .sort((left, right) => parseApiInstant(left.timeline_time) - parseApiInstant(right.timeline_time) || Number(left.id) - Number(right.id))
    .map(snapshot => {
      const time = parseApiInstant(snapshot.timeline_time).getTime();
      const bucket = props.buckets.find((item, index) => {
        const bucketStart = parseApiInstant(item.start).getTime();
        const bucketEnd = parseApiInstant(item.end).getTime();
        return time >= bucketStart && (time < bucketEnd || (index === props.buckets.length - 1 && time <= bucketEnd));
      });
      const key = bucket?.start || `outside-${snapshot.timeline_time}`;
      const lane = lanes.get(key) || 0;
      lanes.set(key, lane + 1);
      return { ...snapshot, lane };
    });
});

const timelineStyle = computed(() => {
  const largestLane = snapshotMarkers.value.reduce((largest, marker) => Math.max(largest, marker.lane), 0);
  return { '--timeline-height': `${Math.max(152, 34 + (largestLane + 1) * 18)}px` };
});

function formatTime(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(parseApiInstant(value));
}

function emitRange() {
  const start = toIso(startInput.value);
  const end = toIso(endInput.value);
  if (!start || !end || parseApiInstant(start) >= parseApiInstant(end)) return;
  emit('change-range', { start, end });
}

function selectAtRatio(rawRatio) {
  const ratio = Math.min(1, Math.max(0, Number(rawRatio)));
  position.value = Math.round(ratio * 1000) / 10;
  const time = new Date(startMs.value + (endMs.value - startMs.value) * ratio).toISOString();
  emit('select-time', time);
}

function selectBucket(bucket) {
  selectAtRatio(timeRatio(parseApiInstant(bucket.start).getTime()));
}

function selectSnapshot(snapshot) {
  selectAtRatio(timeRatio(parseApiInstant(snapshot.timeline_time).getTime()));
}

function bucketStyle(bucket) {
  const left = timeRatio(parseApiInstant(bucket.start).getTime()) * 100;
  const right = timeRatio(parseApiInstant(bucket.end).getTime()) * 100;
  const count = Number(bucket.count) || 0;
  return {
    left: `${left}%`,
    width: `${Math.max(0, right - left)}%`,
    height: `${count ? Math.max(3, (count / maxCount.value) * 100) : 1}%`,
  };
}

function markerStyle(snapshot) {
  return {
    left: `${timeRatio(parseApiInstant(snapshot.timeline_time).getTime()) * 100}%`,
    bottom: `${4 + snapshot.lane * 18}px`,
  };
}

function shift(minutes) {
  const selected = props.selectedTime ? parseApiInstant(props.selectedTime).getTime() : endMs.value;
  const time = Math.min(endMs.value, Math.max(startMs.value, selected + minutes * 60 * 1000));
  selectAtRatio((time - startMs.value) / timeSpan.value);
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

onBeforeUnmount(() => clearInterval(playbackTimer));
</script>

<template>
  <section class="card timeline-card">
    <div class="section-heading">
      <div>
        <h2>时间轴</h2>
        <p>所有时间按 Asia/Shanghai 显示；柱状图、快照节点和滑块共用同一时间坐标。</p>
      </div>
      <span v-if="loading" class="loading">加载中…</span>
    </div>

    <div class="range-controls">
      <label>开始 <input v-model="startInput" type="datetime-local" @change="emitRange" /></label>
      <label>结束 <input v-model="endInput" type="datetime-local" @change="emitRange" /></label>
      <button class="secondary" @click="emitRange">刷新区间</button>
    </div>

    <div class="timeline-shell">
      <div class="timeline-bars" :style="timelineStyle" aria-label="修改密度时间轴">
        <button
          v-for="bucket in buckets"
          :key="bucket.start"
          class="timeline-bar"
          :class="{ empty: !Number(bucket.count) }"
          :title="`${formatTime(bucket.start)} 至 ${formatTime(bucket.end)}：${bucket.count} 次修改`"
          :style="bucketStyle(bucket)"
          @click="selectBucket(bucket)"
        ></button>
        <button
          v-for="snapshot in snapshotMarkers"
          :key="snapshot.id"
          class="snapshot-marker"
          :style="markerStyle(snapshot)"
          :title="`快照 #${snapshot.id} · 事件 ${snapshot.event_id} · 画布时间 ${formatTime(snapshot.timeline_time)}`"
          @click="selectSnapshot(snapshot)"
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
.timeline-shell { margin-top: 18px; }.timeline-bars { position: relative; height: var(--timeline-height); border: 1px solid #dbe3ee; border-radius: 9px 9px 0 0; overflow: hidden; background: linear-gradient(to bottom, #f8fbff, #fff); }.timeline-bar { position: absolute; bottom: 0; min-width: 1px; border: 0; border-left: 1px solid #ffffff80; background: linear-gradient(#60a5fa, #2563eb); cursor: pointer; border-radius: 2px 2px 0 0; }.timeline-bar.empty { background: #dbeafe; }.timeline-bar:hover { background: #1d4ed8; }.snapshot-marker { position: absolute; transform: translateX(-50%); z-index: 2; color: #b45309; border: 0; background: transparent; cursor: pointer; font-size: 14px; line-height: 14px; padding: 0; text-shadow: 0 1px #fff; }.timeline-labels { display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-top: 5px; }.scrubber-row input { flex: 1; min-width: 200px; accent-color: #2563eb; } output { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #334155; }
@media (max-width: 640px) { .card { padding: 16px; }.range-controls label,.range-controls input { width: 100%; }.timeline-bars { min-height: 115px; } }
</style>

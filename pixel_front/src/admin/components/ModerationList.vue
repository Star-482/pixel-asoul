<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  items: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['block', 'unblock']);
const manualVisitorId = ref('');
const manualMinutes = ref(30);

const relevantItems = computed(() => props.items.filter(item => (
  item.status !== 'normal' || Number(item.strike_count) > 0
)));

function formatTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value));
}

function requestBlock(visitorId, fallback = 30) {
  const value = window.prompt('封禁时长（分钟，1–1440）', String(fallback));
  if (value === null) return;
  const minutes = Number(value);
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 1440) return;
  emit('block', { visitorId, minutes });
}

function manualBlock() {
  if (!manualVisitorId.value.trim()) return;
  emit('block', { visitorId: manualVisitorId.value.trim(), minutes: Number(manualMinutes.value) || 30 });
}

async function copyVisitorId(visitorId) {
  try { await navigator.clipboard.writeText(visitorId); } catch { /* clipboard access is optional */ }
}
</script>

<template>
  <section class="card">
    <div class="section-heading"><div><h2>风控与封禁</h2><p>访客标识在页面上默认掩码显示；封禁、覆盖冷却和观察状态均会保留审计记录。</p></div></div>
    <form class="manual-block" @submit.prevent="manualBlock">
      <input v-model.trim="manualVisitorId" placeholder="手动封禁：访客 UUID" aria-label="访客 UUID" />
      <input v-model.number="manualMinutes" type="number" min="1" max="1440" aria-label="封禁分钟数" />
      <button :disabled="busy">手动封禁</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead><tr><th>访客</th><th>状态</th><th>封禁至</th><th>覆盖冷却 / 观察</th><th>记录</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in relevantItems" :key="row.visitor_id">
            <td><button class="visitor" :title="row.visitor_id" @click="copyVisitorId(row.visitor_id)">{{ row.display_visitor_id }}</button></td>
            <td><span class="status" :class="row.status">{{ row.status === 'blocked' ? '已封禁' : row.status === 'overwrite_cooldown' ? '覆盖冷却' : row.status === 'observing' ? '观察中' : '正常（有历史）' }}</span></td>
            <td>{{ formatTime(row.blocked_until) }}</td>
            <td>{{ formatTime(row.overwrite_cooldown_until || row.overwrite_watch_until) }}</td>
            <td>{{ row.strike_count }} 次处罚</td>
            <td class="actions"><button v-if="row.status === 'blocked'" class="secondary" :disabled="busy" @click="emit('unblock', row.visitor_id)">解除</button><button v-else class="secondary" :disabled="busy" @click="requestBlock(row.visitor_id)">封禁</button></td>
          </tr>
          <tr v-if="!relevantItems.length"><td colspan="6" class="empty">当前没有风控或封禁记录。</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.card { background:#fff; border:1px solid #dbe3ee; border-radius:14px; padding:22px; box-shadow:0 4px 16px #1720330d; }.section-heading { display:flex; justify-content:space-between; gap:16px; }.section-heading h2 { margin:0; font-size:20px; }.section-heading p { margin:6px 0 0; color:#64748b; font-size:13px; line-height:1.5; }.manual-block { display:grid; grid-template-columns:minmax(220px,1fr) 110px auto; gap:8px; margin:16px 0; }input,button { font:inherit; box-sizing:border-box; }input { min-width:0; padding:8px; border:1px solid #cbd5e1; border-radius:7px; }button { border:1px solid #2563eb; background:#2563eb; color:#fff; border-radius:7px; padding:8px 10px; cursor:pointer; }button:disabled { opacity:.55; cursor:not-allowed; }.table-wrap { overflow:auto; }table { width:100%; border-collapse:collapse; min-width:800px; font-size:13px; }th,td { padding:10px 8px; border-bottom:1px solid #e2e8f0; text-align:left; white-space:nowrap; }.visitor { padding:0; color:#1d4ed8; background:none; border:0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }.status { display:inline-block; padding:3px 7px; border-radius:999px; font-size:12px; }.blocked { background:#fee2e2; color:#b91c1c; }.overwrite_cooldown { background:#fef3c7; color:#92400e; }.observing { background:#dbeafe; color:#1d4ed8; }.secondary { background:#fff; color:#1e40af; border-color:#bfdbfe; }.empty { color:#64748b; text-align:center; padding:22px; }.actions { text-align:right; }
@media (max-width:640px) { .card { padding:16px; }.manual-block { grid-template-columns:1fr 90px; }.manual-block button { grid-column:1 / -1; } }
</style>

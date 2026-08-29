<script setup>
import { computed, ref } from 'vue';

const token = ref('');
const csrf = ref(sessionStorage.getItem('pixel_admin_csrf') || '');
const loggedIn = ref(Boolean(csrf.value));
const error = ref('');
const timeline = ref([]);
const preview = ref(null);
const targetEventId = ref('');
const mode = ref('selective');
const filters = ref({ x_min: 0, y_min: 0, x_max: 999, y_max: 999 });
const plan = ref(null);
const moderation = ref([]);
const actions = ref([]);
const readOnly = ref(false);

const headers = computed(() => ({ 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.value }));

async function login() {
  error.value = '';
  const response = await fetch('/api/v2/admin/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ token: token.value }) });
  if (!response.ok) { error.value = '管理员令牌无效'; return; }
  csrf.value = (await response.json()).csrf_token;
  sessionStorage.setItem('pixel_admin_csrf', csrf.value);
  token.value = '';
  loggedIn.value = true;
  await refresh();
}

async function request(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { ...headers.value, ...(options.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail?.message || '请求失败');
  return response.status === 204 ? null : response.json();
}

async function refresh() {
  try {
    const [timelineResult, moderationResult, actionsResult] = await Promise.all([
      request('/api/v2/admin/timeline'), request('/api/v2/admin/moderation'), request('/api/v2/admin/actions'),
    ]);
    timeline.value = timelineResult.buckets;
    moderation.value = moderationResult.items;
    actions.value = actionsResult.items;
  } catch (cause) { error.value = cause.message; }
}

async function createPreview() {
  try {
    preview.value = await request('/api/v2/admin/timeline/previews', { method: 'POST', body: JSON.stringify({ target_event_id: Number(targetEventId.value) }) });
  } catch (cause) { error.value = cause.message; }
}

async function makePlan() {
  try {
    plan.value = await request('/api/v2/admin/restore-plans', { method: 'POST', body: JSON.stringify({ mode: mode.value, target_event_id: Number(targetEventId.value), filters: filters.value }) });
  } catch (cause) { error.value = cause.message; }
}

async function executePlan() {
  if (!plan.value || !confirm(`确认恢复 ${plan.value.affected_pixels} 个像素？`)) return;
  try { await request(`/api/v2/admin/restore-plans/${plan.value.id}/execute`, { method: 'POST', body: '{}' }); await refresh(); plan.value = null; } catch (cause) { error.value = cause.message; }
}

async function setReadOnly() {
  try { await request('/api/v2/admin/canvas/read-only', { method: 'PUT', body: JSON.stringify({ enabled: readOnly.value }) }); } catch (cause) { error.value = cause.message; }
}
</script>

<template>
  <main class="admin-page">
    <section v-if="!loggedIn" class="login-card">
      <h1>Pixel Canvas 管理工具</h1>
      <p>管理员令牌仅用于本次登录，浏览器不会保存原始令牌。</p>
      <input v-model="token" type="password" autocomplete="current-password" placeholder="管理员令牌" @keyup.enter="login" />
      <button @click="login">登录</button>
      <p v-if="error" class="error">{{ error }}</p>
    </section>
    <template v-else>
      <header><h1>画布管理</h1><button @click="refresh">刷新</button></header>
      <p v-if="error" class="error">{{ error }}</p>
      <section class="card"><h2>全局开关</h2><label><input v-model="readOnly" type="checkbox" @change="setReadOnly" /> 维护只读</label></section>
      <section class="card"><h2>时间轴（Asia/Shanghai）</h2><div class="timeline"><span v-for="bucket in timeline" :key="bucket.time" :title="`${bucket.time}: ${bucket.count}`" :style="{ height: `${Math.max(4, Math.min(100, bucket.count))}px` }"></span></div></section>
      <section class="card"><h2>历史预览与恢复</h2><label>目标事件 <input v-model="targetEventId" type="number" min="0" /></label><button @click="createPreview">生成预览</button><img v-if="preview" :src="preview.url" alt="历史画布预览" class="preview" /><div class="filter-grid"><label>模式 <select v-model="mode"><option value="selective">撤销可疑事件</option><option value="exact">精确恢复区域</option></select></label><label>X 起点 <input v-model.number="filters.x_min" type="number" /></label><label>Y 起点 <input v-model.number="filters.y_min" type="number" /></label><label>X 终点 <input v-model.number="filters.x_max" type="number" /></label><label>Y 终点 <input v-model.number="filters.y_max" type="number" /></label></div><button @click="makePlan">创建恢复计划</button><button v-if="plan" class="danger" @click="executePlan">执行 {{ plan.affected_pixels }} 像素恢复</button></section>
      <section class="card"><h2>风控状态</h2><table><thead><tr><th>访客</th><th>封禁至</th><th>验证码</th><th>次数</th></tr></thead><tbody><tr v-for="row in moderation" :key="row.visitor_id"><td>{{ row.visitor_id }}</td><td>{{ row.blocked_until || '-' }}</td><td>{{ row.challenge_required_until || '-' }}</td><td>{{ row.strike_count }}</td></tr></tbody></table></section>
      <section class="card"><h2>操作审计</h2><ul><li v-for="row in actions" :key="row.id">{{ row.created_at }} · {{ row.admin_id }} · {{ row.action }}</li></ul></section>
    </template>
  </main>
</template>

<style scoped>
.admin-page { max-width: 1100px; margin: 0 auto; padding: 28px; color: #172033; }.login-card,.card { background:#fff; border:1px solid #dbe3ee; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 2px 8px #1720330d; }.login-card { max-width:420px; margin:10vh auto; }.login-card input { width:100%; box-sizing:border-box; margin:12px 0; }input,select,button { padding:8px 10px; border-radius:6px; border:1px solid #b9c5d5; margin:4px; }button { background:#2563eb; border-color:#2563eb; color:white; cursor:pointer; }.danger { background:#b91c1c; border-color:#b91c1c; }.error { color:#b91c1c; }.timeline { height:110px; display:flex; align-items:flex-end; gap:2px; border-bottom:1px solid #cbd5e1; }.timeline span { min-width:3px; flex:1; background:#2563eb; }.preview { display:block; max-width:100%; width:500px; image-rendering:pixelated; margin:12px 0; border:1px solid #cbd5e1; }.filter-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; margin:10px 0; }table { width:100%; border-collapse:collapse; }th,td { text-align:left; padding:8px; border-bottom:1px solid #e2e8f0; }header { display:flex; align-items:center; justify-content:space-between; }
</style>

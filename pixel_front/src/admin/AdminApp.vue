<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import AuditLog from './components/AuditLog.vue';
import ModerationList from './components/ModerationList.vue';
import RestorePanel from './components/RestorePanel.vue';
import Timeline from './components/Timeline.vue';

const token = ref('');
const csrf = ref(sessionStorage.getItem('pixel_admin_csrf') || '');
const loggedIn = ref(Boolean(csrf.value));
const error = ref('');
const notice = ref('');
const loading = ref(false);
const actionBusy = ref(false);
const restorePanel = ref(null);
const status = ref({ canvas: { width: 1000, height: 1000, head_event_id: 0, draw_enabled: false }, stats: {} });
const timeline = ref({ buckets: [], snapshots: [] });
const moderation = ref({ items: [] });
const actions = ref([]);
const preview = ref(null);
const plan = ref(null);
const operation = ref(null);
const selectedTime = ref('');
const readOnly = ref(false);
const timelineRange = ref(defaultRange());
let previewTimer = null;
let operationTimer = null;

const canvas = computed(() => status.value.canvas || { width: 1000, height: 1000, head_event_id: 0, draw_enabled: false });
const stats = computed(() => status.value.stats || {});

function defaultRange() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

function errorMessage(payload) {
  const detail = payload?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail.message === 'string') return detail.message;
  if (typeof payload?.message === 'string') return payload.message;
  return '请求失败，请稍后重试';
}

async function request(path, { method = 'GET', data, mutation = false } = {}) {
  const headers = {};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (mutation) headers['X-CSRF-Token'] = csrf.value;
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers,
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      csrf.value = '';
      sessionStorage.removeItem('pixel_admin_csrf');
      loggedIn.value = false;
    }
    throw new Error(errorMessage(payload));
  }
  return response.status === 204 ? null : response.json();
}

async function login() {
  error.value = '';
  if (!token.value) return;
  try {
    const response = await fetch('/api/v2/admin/session', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: token.value }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(payload));
    csrf.value = payload.csrf_token;
    sessionStorage.setItem('pixel_admin_csrf', csrf.value);
    token.value = '';
    loggedIn.value = true;
    notice.value = '登录成功。管理员令牌未保存在浏览器中。';
    await refresh();
  } catch (cause) { error.value = cause.message; }
}

async function logout() {
  try { await request('/api/v2/admin/session', { method: 'DELETE', mutation: true }); } catch { /* cookie may already have expired */ }
  csrf.value = '';
  sessionStorage.removeItem('pixel_admin_csrf');
  loggedIn.value = false;
  notice.value = '';
}

async function loadTimeline() {
  const params = new URLSearchParams(timelineRange.value);
  const data = await request(`/api/v2/admin/timeline?${params.toString()}`);
  timeline.value = data;
}

async function refresh() {
  if (!loggedIn.value) return;
  loading.value = true;
  error.value = '';
  try {
    const [nextStatus, , nextModeration, nextActions] = await Promise.all([
      request('/api/v2/admin/status'),
      loadTimeline(),
      request('/api/v2/admin/moderation'),
      request('/api/v2/admin/actions'),
    ]);
    status.value = nextStatus;
    readOnly.value = !nextStatus.canvas.draw_enabled;
    moderation.value = nextModeration;
    actions.value = nextActions.items;
  } catch (cause) { error.value = cause.message; } finally { loading.value = false; }
}

async function changeRange(range) {
  timelineRange.value = range;
  try { await loadTimeline(); } catch (cause) { error.value = cause.message; }
}

function selectTimelineTime(time) {
  selectedTime.value = time;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => restorePanel.value?.setTargetTime(time), 250);
}

async function createPreview(payload) {
  actionBusy.value = true;
  error.value = '';
  try {
    preview.value = await request('/api/v2/admin/timeline/previews', { method: 'POST', data: payload, mutation: true });
    plan.value = null;
  } catch (cause) { error.value = cause.message; } finally { actionBusy.value = false; }
}

async function createPlan(payload) {
  actionBusy.value = true;
  error.value = '';
  try {
    plan.value = await request('/api/v2/admin/restore-plans', { method: 'POST', data: payload, mutation: true });
    notice.value = `已生成恢复计划：${plan.value.affected_pixels.toLocaleString()} 个像素。`;
  } catch (cause) { error.value = cause.message; } finally { actionBusy.value = false; }
}

async function executePlan({ confirmation_text }) {
  if (!plan.value) return;
  if (!window.confirm(`确认执行恢复计划？将写入 ${plan.value.affected_pixels.toLocaleString()} 条新的像素历史。`)) return;
  actionBusy.value = true;
  error.value = '';
  try {
    const result = await request(`/api/v2/admin/restore-plans/${plan.value.id}/execute`, {
      method: 'POST', data: { confirmation_text }, mutation: true,
    });
    if (result.status === 'queued') {
      operation.value = result;
      notice.value = `大范围恢复已进入维护队列，预计处理 ${result.affected_pixels.toLocaleString()} 个像素。`;
      monitorOperation(result.id);
    } else {
      notice.value = `恢复完成：${result.affected_pixels.toLocaleString()} 个像素已写入新的历史记录。`;
      await refresh();
    }
    plan.value = null;
    preview.value = null;
  } catch (cause) { error.value = cause.message; } finally { actionBusy.value = false; }
}

async function monitorOperation(operationId) {
  clearInterval(operationTimer);
  async function poll() {
    try {
      const result = await request(`/api/v2/admin/restore-operations/${operationId}`);
      operation.value = result;
      if (result.status === 'completed' || result.status === 'failed') {
        clearInterval(operationTimer);
        operationTimer = null;
        notice.value = result.status === 'completed'
          ? `大范围恢复完成：${result.affected_pixels.toLocaleString()} 个像素已恢复。`
          : '大范围恢复失败，请查看操作审计。';
        await refresh();
      }
    } catch (cause) {
      clearInterval(operationTimer);
      operationTimer = null;
      error.value = cause.message;
    }
  }
  await poll();
  if (operation.value?.status === 'queued' || operation.value?.status === 'running') {
    operationTimer = setInterval(poll, 1000);
  }
}

async function setReadOnly() {
  actionBusy.value = true;
  try {
    const result = await request('/api/v2/admin/canvas/read-only', { method: 'PUT', data: { enabled: readOnly.value }, mutation: true });
    status.value = { ...status.value, canvas: { ...status.value.canvas, draw_enabled: result.draw_enabled } };
    notice.value = result.draw_enabled ? '已恢复绘制。' : '已开启维护只读，新的绘制请求会被拒绝。';
  } catch (cause) {
    readOnly.value = !readOnly.value;
    error.value = cause.message;
  } finally { actionBusy.value = false; }
}

async function blockVisitor({ visitorId, minutes }) {
  actionBusy.value = true;
  try {
    await request(`/api/v2/admin/moderation/${encodeURIComponent(visitorId)}/block`, { method: 'POST', data: { minutes }, mutation: true });
    notice.value = '访客已封禁。';
    await refresh();
  } catch (cause) { error.value = cause.message; } finally { actionBusy.value = false; }
}

async function unblockVisitor(visitorId) {
  if (!window.confirm('确认解除该访客的封禁和验证码限制？')) return;
  actionBusy.value = true;
  try {
    await request(`/api/v2/admin/moderation/${encodeURIComponent(visitorId)}/unblock`, { method: 'POST', data: {}, mutation: true });
    notice.value = '已解除访客限制。';
    await refresh();
  } catch (cause) { error.value = cause.message; } finally { actionBusy.value = false; }
}

onMounted(async () => { if (loggedIn.value) await refresh(); });
onBeforeUnmount(() => { clearTimeout(previewTimer); clearInterval(operationTimer); });
</script>

<template>
  <main class="admin-page">
    <section v-if="!loggedIn" class="login-card">
      <span class="eyebrow">Pixel Canvas</span>
      <h1>画布管理后台</h1>
      <p>使用管理员令牌登录。令牌只用于本次提交，浏览器仅保存短期会话和 CSRF 令牌。</p>
      <input v-model="token" type="password" autocomplete="current-password" placeholder="管理员令牌" @keyup.enter="login" />
      <button @click="login">安全登录</button>
      <p v-if="error" class="message error">{{ error }}</p>
    </section>

    <template v-else>
      <header class="page-header">
        <div><span class="eyebrow">Pixel Canvas · 管理员</span><h1>画布管理</h1></div>
        <div class="header-actions"><button class="secondary" :disabled="loading" @click="refresh">{{ loading ? '刷新中…' : '刷新数据' }}</button><button class="secondary" @click="logout">退出登录</button></div>
      </header>

      <p v-if="error" class="message error">{{ error }}</p>
      <p v-if="notice" class="message success">{{ notice }}</p>

      <section class="status-grid">
        <div class="status-card"><span>画布状态</span><strong :class="canvas.draw_enabled ? 'good' : 'danger-text'">{{ canvas.draw_enabled ? '可绘制' : '维护只读' }}</strong><small>事件 #{{ canvas.head_event_id.toLocaleString() }}</small></div>
        <div class="status-card"><span>当前在线</span><strong>{{ stats.online_users ?? 0 }}</strong><small>累计访问 {{ (stats.total_visits ?? 0).toLocaleString() }}</small></div>
        <div class="status-card"><span>累计用户绘制</span><strong>{{ (stats.total_placed_pixels ?? 0).toLocaleString() }}</strong><small>覆盖滥用以递进冷却处置</small></div>
      </section>

      <section class="card read-only-card"><div><h2>全局维护开关</h2><p>开启后服务端会拒绝所有新的绘制请求，并实时通知已连接用户。</p></div><label class="switch"><input v-model="readOnly" type="checkbox" :disabled="actionBusy" @change="setReadOnly" /><span></span>维护只读</label></section>

      <Timeline :buckets="timeline.buckets" :snapshots="timeline.snapshots" :start="timelineRange.start" :end="timelineRange.end" :selected-time="selectedTime" :loading="loading" @change-range="changeRange" @select-time="selectTimelineTime" />
      <RestorePanel ref="restorePanel" :canvas="canvas" :preview="preview" :plan="plan" :operation="operation" :selected-time="selectedTime" :busy="actionBusy" @create-preview="createPreview" @create-plan="createPlan" @execute-plan="executePlan" />
      <ModerationList :items="moderation.items" :busy="actionBusy" @block="blockVisitor" @unblock="unblockVisitor" />
      <AuditLog :items="actions" />
    </template>
  </main>
</template>

<style scoped>
.admin-page { max-width:1180px; margin:0 auto; padding:32px 24px 56px; color:#172033; }.page-header { display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:20px; }.page-header h1,.login-card h1 { margin:3px 0 0; font-size:34px; letter-spacing:-.04em; }.eyebrow { color:#2563eb; font-size:12px; letter-spacing:.08em; font-weight:700; text-transform:uppercase; }.header-actions { display:flex; gap:8px; }.secondary { background:#fff; border:1px solid #bfdbfe; color:#1e40af; }.status-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-bottom:16px; }.status-card,.card,.login-card { background:#fff; border:1px solid #dbe3ee; border-radius:14px; box-shadow:0 4px 16px #1720330d; }.status-card { display:grid; gap:5px; padding:18px; }.status-card span,.status-card small { color:#64748b; font-size:13px; }.status-card strong { font-size:25px; }.good { color:#15803d; }.danger-text { color:#b91c1c; }.card { padding:20px; margin-bottom:16px; }.read-only-card { display:flex; justify-content:space-between; align-items:center; gap:16px; }.read-only-card h2 { margin:0; font-size:20px; }.read-only-card p { margin:5px 0 0; color:#64748b; font-size:13px; }.switch { display:flex; align-items:center; gap:8px; color:#334155; white-space:nowrap; }.switch input { accent-color:#b91c1c; width:18px; height:18px; }.login-card { max-width:440px; margin:12vh auto; padding:28px; display:grid; gap:14px; }.login-card p { color:#64748b; line-height:1.6; margin:0; }.login-card input { padding:10px; border:1px solid #cbd5e1; border-radius:8px; font:inherit; }.login-card button,button { border:1px solid #2563eb; border-radius:8px; padding:9px 12px; background:#2563eb; color:#fff; font:inherit; cursor:pointer; }button:disabled { opacity:.55; cursor:not-allowed; }.message { padding:10px 12px; border-radius:9px; margin:0 0 16px; font-size:14px; }.error { color:#b91c1c; background:#fee2e2; border:1px solid #fecaca; }.success { color:#166534; background:#dcfce7; border:1px solid #bbf7d0; }
@media (max-width:760px) { .admin-page { padding:20px 14px 42px; }.page-header { align-items:flex-start; flex-direction:column; }.page-header h1,.login-card h1 { font-size:28px; }.status-grid { grid-template-columns:1fr; }.read-only-card { align-items:flex-start; flex-direction:column; }.header-actions { width:100%; }.header-actions button { flex:1; } }
</style>

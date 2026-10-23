<script setup>
defineProps({ items: { type: Array, default: () => [] } });

function formatTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(value));
}

function detailText(details) {
  return Object.entries(details || {}).map(([key, value]) => `${key}=${String(value)}`).join(' · ') || '—';
}
</script>

<template>
  <section class="card">
    <div class="section-heading"><div><h2>操作审计</h2><p>管理员登录、封禁、全局开关和恢复计划均记录在此。</p></div><span>{{ items.length }} 条</span></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-for="row in items" :key="row.id"><td>{{ formatTime(row.created_at) }}</td><td>{{ row.admin_id }}</td><td><code>{{ row.action }}</code></td><td>{{ detailText(row.details) }}</td></tr>
          <tr v-if="!items.length"><td colspan="4" class="empty">尚无管理员操作记录。</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.card { background:#fff; border:1px solid #dbe3ee; border-radius:14px; padding:22px; box-shadow:0 4px 16px #1720330d; }.section-heading { display:flex; justify-content:space-between; gap:16px; }.section-heading h2 { margin:0; font-size:20px; }.section-heading p,.section-heading span { margin:6px 0 0; color:#64748b; font-size:13px; }.table-wrap { overflow:auto; margin-top:14px; }table { width:100%; min-width:700px; border-collapse:collapse; font-size:13px; }th,td { padding:10px 8px; border-bottom:1px solid #e2e8f0; text-align:left; vertical-align:top; }code { color:#1d4ed8; }.empty { text-align:center; color:#64748b; padding:22px; }@media (max-width:640px) { .card { padding:16px; } }
</style>

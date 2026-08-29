<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  archiveSemAccount,
  createCustomer,
  fetchCustomers,
  fetchSemIdentityRepairCandidates,
  fetchSemIdentityRepairPreview,
  setCustomerModule,
  updateCustomer,
} from '../../api/moduleAssets'
import { session } from '../../store/session'

const router = useRouter()

const loading = ref(false)
const customers = ref([])
const identitySummary = ref({ checked_customers: 0, checked_accounts: 0, errors: 0, warnings: 0, healthy: true })
const visible = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', industry: '', business_desc: '', modules: ['sem'] })
const repairVisible = ref(false)
const repairLoading = ref(false)
const repairCandidates = ref({ groups: [], summary: {} })
const repairPreview = ref(null)
const repairForm = reactive({ source_tenant_id: null, target_tenant_id: null })
const moduleLabels = { sem: 'SEM', seo: 'SEO', geo: 'GEO' }
const editingCustomer = computed(() => customers.value.find((row) => row.id === editingId.value))
const canPreviewRepair = computed(() => (
  repairForm.source_tenant_id
  && repairForm.target_tenant_id
  && repairForm.source_tenant_id !== repairForm.target_tenant_id
))

function moduleRow(row, code) {
  return row.modules?.find((item) => item.module_code === code)
}

async function load() {
  loading.value = true
  try {
    const result = await fetchCustomers()
    customers.value = result.customers || []
    identitySummary.value = result.identity_summary || { checked_customers: 0, checked_accounts: 0, errors: 0, warnings: 0, healthy: true }
  }
  catch (error) { ElMessage.error(error.message) }
  finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', industry: '', business_desc: '', modules: ['sem'] })
  visible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, industry: row.industry || '', business_desc: row.business_desc || '', modules: row.modules.filter((m) => m.available).map((m) => m.module_code) })
  visible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写客户名称')
  let nameChangeReason = null
  const boundNameChanged = Boolean(
    editingCustomer.value?.identity_locked
    && form.name.trim() !== editingCustomer.value.name,
  )
  if (boundNameChanged) {
    try {
      const result = await ElMessageBox.prompt(
        '该客户已绑定推广账户。请填写本次客户更名原因；账户归属错误不能通过改名修复。',
        '受控客户更名',
        {
          confirmButtonText: '下一步',
          cancelButtonText: '取消',
          inputPlaceholder: '至少填写 4 个字，例如：客户完成品牌更名',
          inputValidator: (value) => String(value || '').trim().length >= 4 || '请填写至少 4 个字的更名原因',
        },
      )
      nameChangeReason = result.value.trim()
      await ElMessageBox.confirm(
        `确认将“${editingCustomer.value.name}”更名为“${form.name.trim()}”？推广账户绑定不会改变，操作将写入审计日志。`,
        '最终确认',
        { type: 'warning', confirmButtonText: '确认更名', cancelButtonText: '返回检查' },
      )
    } catch {
      return
    }
  }
  try {
    if (editingId.value) {
      await updateCustomer(editingId.value, {
        name: form.name,
        industry: form.industry || null,
        business_desc: form.business_desc || null,
        confirm_bound_name_change: boundNameChanged,
        name_change_reason: nameChangeReason,
      })
      for (const code of Object.keys(moduleLabels)) {
        await setCustomerModule(editingId.value, code, { status: form.modules.includes(code) ? 'active' : 'suspended' })
      }
    } else {
      await createCustomer({ name: form.name, industry: form.industry || null, business_desc: form.business_desc || null, modules: form.modules })
    }
    visible.value = false
    ElMessage.success('客户与模块配置已保存')
    await load()
    session.requestTenantReload()
  } catch (error) { ElMessage.error(error.message) }
}

async function archiveAccount(row, account) {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(
      `即将归档账户绑定“${account.username} · UCID ${account.ucid}”。归档不会删除历史推广数据，`
      + '只是让该账户不再作为客户当前有效的推广账户。请填写归档原因（例如：账户归属核实为其他客户）。',
      '归档错误账户绑定',
      {
        confirmButtonText: '下一步',
        cancelButtonText: '取消',
        inputPlaceholder: '至少填写 4 个字',
        inputValidator: (value) => String(value || '').trim().length >= 4 || '请填写至少 4 个字的归档原因',
      },
    )
    reason = result.value.trim()
    await ElMessageBox.confirm(
      `确认归档“${row.name}”下的账户“${account.username} · UCID ${account.ucid}”？此操作会写入审计日志，且不可在前端撤销。`,
      '最终确认',
      { type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '返回检查' },
    )
  } catch {
    return
  }
  try {
    await archiveSemAccount(row.id, account.id, reason)
    ElMessage.success('账户绑定已归档')
    await load()
    session.requestTenantReload()
  } catch (error) { ElMessage.error(error.message) }
}

function rebindAccount(row) {
  router.push({ path: '/onboarding', query: { tenant_id: row.id, rebind: '1' } })
}

async function openRepairPreview() {
  repairVisible.value = true
  repairPreview.value = null
  Object.assign(repairForm, { source_tenant_id: null, target_tenant_id: null })
  repairLoading.value = true
  try {
    repairCandidates.value = await fetchSemIdentityRepairCandidates()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    repairLoading.value = false
  }
}

async function runRepairPreview() {
  if (!canPreviewRepair.value) return ElMessage.warning('请选择两个不同的客户')
  repairLoading.value = true
  repairPreview.value = null
  try {
    repairPreview.value = await fetchSemIdentityRepairPreview(
      repairForm.source_tenant_id,
      repairForm.target_tenant_id,
    )
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    repairLoading.value = false
  }
}

function repairActionLabel(row) {
  if (row.proposed_action === 'manual_identity_resolution_required') {
    return '人工决定保留/归档，禁止直接迁移身份记录'
  }
  if (row.proposed_action === 'preserve_audit_provenance_manual_review') {
    return '保留原始审计归属，制定专项处理方案'
  }
  return '审核唯一约束后再迁移 tenant_id'
}

onMounted(load)
</script>

<template>
  <div class="module-page" v-loading="loading">
    <header class="page-head">
      <div><h2>客户与模块</h2><p>平台级客户主档仅由超级管理员维护；模块内只显示已开通该模块的客户。</p></div>
      <div class="head-actions">
        <el-button @click="load">重新检查归属</el-button>
        <el-button type="warning" plain @click="openRepairPreview">重复客户只读预演</el-button>
        <el-button type="primary" @click="openCreate">新建客户</el-button>
      </div>
    </header>
    <el-alert
      :type="identitySummary.healthy ? 'success' : identitySummary.errors ? 'error' : 'warning'"
      :title="identitySummary.healthy ? `归属检查通过：${identitySummary.checked_customers} 个客户、${identitySummary.checked_accounts} 个推广账户未发现结构性冲突` : `归属检查发现 ${identitySummary.errors} 个错误、${identitySummary.warnings} 个提醒；本页只报告，不会自动修改数据`"
      :closable="false"
      show-icon
      class="identity-summary"
    />
    <el-table :data="customers" border>
      <el-table-column prop="name" label="客户" min-width="180" />
      <el-table-column prop="industry" label="行业" min-width="150" />
      <el-table-column label="SEM 推广账户归属" min-width="320">
        <template #default="{ row }">
          <div v-if="row.sem_accounts?.some((a) => a.status !== 'archived')" class="account-bindings">
            <span v-for="account in row.sem_accounts.filter((a) => a.status !== 'archived')" :key="account.id">
              <span class="account-label">
                {{ account.username }} · {{ account.ucid }}
                <small>{{ account.auth_mode === 'oauth' ? 'OAuth' : '自授权' }} · {{ account.status }}</small>
              </span>
              <el-button type="danger" plain size="small" @click="archiveAccount(row, account)">归档</el-button>
            </span>
          </div>
          <span v-else class="unbound">未绑定</span>
          <el-button
            v-if="moduleRow(row, 'sem')?.available"
            type="primary" plain size="small" @click="rebindAccount(row)"
          >重新绑定并授权</el-button>
        </template>
      </el-table-column>
      <el-table-column label="归属检查" min-width="230">
        <template #default="{ row }">
          <el-tag v-if="row.identity_state === 'ok'" type="success">一致</el-tag>
          <div v-else class="identity-issues">
            <el-tag :type="row.identity_state === 'error' ? 'danger' : 'warning'">
              {{ row.identity_state === 'error' ? '存在冲突' : '需要核对' }}
            </el-tag>
            <span v-for="issue in row.identity_issues" :key="`${issue.code}:${issue.ucid || ''}`">{{ issue.message }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column v-for="code in ['sem','seo','geo']" :key="code" :label="moduleLabels[code]" width="105" align="center">
        <template #default="{ row }"><el-tag :type="moduleRow(row, code)?.available ? 'success' : 'info'">{{ moduleRow(row, code)?.available ? '已开通' : '未开通' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">配置</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="visible" :title="editingId ? '配置客户' : '新建客户'" width="560px">
      <el-form label-width="90px">
        <el-alert
          v-if="editingCustomer?.identity_locked"
          title="该客户已绑定百度推广账户。正常品牌更名需填写原因并二次确认；若账户归属错误，必须走人工审核的数据迁移流程。"
          type="warning"
          :closable="false"
          show-icon
          class="identity-alert"
        />
        <el-form-item label="客户名称"><el-input v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="所属行业"><el-input v-model="form.industry" maxlength="100" /></el-form-item>
        <el-form-item label="业务说明"><el-input v-model="form.business_desc" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="开通模块"><el-checkbox-group v-model="form.modules"><el-checkbox v-for="(label, code) in moduleLabels" :key="code" :value="code">{{ label }}</el-checkbox></el-checkbox-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="repairVisible" title="SEM 重复客户只读检测与修复预演" width="900px">
      <div v-loading="repairLoading" class="repair-preview">
        <el-alert
          title="这里只读取并对比数据，不会合并客户、迁移记录、删除数据或执行数据库迁移。预演结果不能直接执行。"
          type="warning"
          :closable="false"
          show-icon
        />
        <section class="repair-candidates">
          <h4>同名候选</h4>
          <p v-if="!repairCandidates.groups?.length">当前没有发现规范化名称完全相同的客户组。</p>
          <div v-for="group in repairCandidates.groups" :key="group.normalized_name" class="candidate-group">
            <b>{{ group.customers.map((item) => `${item.name} (#${item.tenant_id})`).join(' / ') }}</b>
            <small>仅按名称发现候选，不代表可以合并；必须人工确认真实客户和账户归属。</small>
          </div>
        </section>
        <el-form inline class="repair-form">
          <el-form-item label="来源客户（拟迁出）">
            <el-select v-model="repairForm.source_tenant_id" filterable placeholder="选择可能误建的客户" style="width:260px">
              <el-option v-for="row in customers" :key="row.id" :label="`${row.name} (#${row.id})`" :value="row.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="保留客户（正确主档）">
            <el-select v-model="repairForm.target_tenant_id" filterable placeholder="选择拟保留客户" style="width:260px">
              <el-option v-for="row in customers" :key="row.id" :label="`${row.name} (#${row.id})`" :value="row.id" />
            </el-select>
          </el-form-item>
          <el-button type="primary" plain :disabled="!canPreviewRepair" @click="runRepairPreview">生成只读预演</el-button>
        </el-form>
        <template v-if="repairPreview">
          <el-alert
            :type="repairPreview.blockers?.length ? 'error' : 'warning'"
            :title="repairPreview.blockers?.length ? `发现 ${repairPreview.blockers.length} 个阻断项，禁止合并` : '未发现结构性阻断，但仍须数据库专项审核和备份后才能处理'"
            :closable="false"
            show-icon
          />
          <div class="repair-columns">
            <section>
              <h4>来源客户</h4>
              <b>{{ repairPreview.source.name }} (#{{ repairPreview.source.tenant_id }})</b>
              <span>客户主 UCID {{ repairPreview.source.baidu_ucid || '未设置' }}</span>
              <div class="repair-accounts">
                <small v-if="!repairPreview.source.accounts?.length">没有推广账户记录</small>
                <span v-for="account in repairPreview.source.accounts" :key="account.id">
                  {{ account.username }} · UCID {{ account.ucid }} · {{ account.status }} / {{ account.auth_mode }}
                </span>
              </div>
            </section>
            <section>
              <h4>保留客户</h4>
              <b>{{ repairPreview.target.name }} (#{{ repairPreview.target.tenant_id }})</b>
              <span>客户主 UCID {{ repairPreview.target.baidu_ucid || '未设置' }}</span>
              <div class="repair-accounts">
                <small v-if="!repairPreview.target.accounts?.length">没有推广账户记录</small>
                <span v-for="account in repairPreview.target.accounts" :key="account.id">
                  {{ account.username }} · UCID {{ account.ucid }} · {{ account.status }} / {{ account.auth_mode }}
                </span>
              </div>
            </section>
          </div>
          <ul v-if="repairPreview.blockers?.length" class="repair-issues blockers">
            <li v-for="item in repairPreview.blockers" :key="item.code"><b>{{ item.code }}</b>：{{ item.message }}</li>
          </ul>
          <ul v-if="repairPreview.warnings?.length" class="repair-issues">
            <li v-for="item in repairPreview.warnings" :key="item.code"><b>{{ item.code }}</b>：{{ item.message }}</li>
          </ul>
          <el-table :data="repairPreview.proposed_operations" border max-height="330">
            <el-table-column prop="table" label="SEM 表" min-width="210" />
            <el-table-column prop="category" label="类别" width="140" />
            <el-table-column prop="source_rows" label="来源行数" width="100" />
            <el-table-column prop="target_rows" label="目标行数" width="100" />
            <el-table-column label="预演动作" min-width="250">
              <template #default="{ row }">
                {{ repairActionLabel(row) }}
              </template>
            </el-table-column>
          </el-table>
          <p class="repair-safety">migration={{ repairPreview.safety.migration }} · writes={{ repairPreview.safety.writes_performed }} · execution_endpoint={{ repairPreview.safety.execution_endpoint_available ? 'enabled' : 'disabled' }}</p>
        </template>
      </div>
      <template #footer><el-button @click="repairVisible=false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.module-page{padding:24px}.page-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px}.page-head h2{margin:0 0 7px;font-size:24px}.page-head p{margin:0;color:#6b7280}.head-actions{display:flex;gap:8px}.identity-summary{margin-bottom:16px}.account-bindings{display:grid;gap:5px;margin-bottom:6px}.account-bindings>span{display:flex;justify-content:space-between;align-items:center;gap:10px}.account-label{display:flex;flex-direction:column}.account-bindings small,.unbound{color:#8b95a5}.identity-issues{display:grid;justify-items:start;gap:5px}.identity-issues span{color:#8a4b08;font-size:12px;line-height:1.35}.identity-alert{margin-bottom:16px}.repair-preview{display:grid;gap:16px}.repair-candidates h4,.repair-columns h4{margin:0 0 6px}.repair-candidates p{margin:0;color:#6b7280}.candidate-group{display:grid;gap:3px;padding:10px 12px;margin-top:8px;border:1px solid #e5e7eb;border-radius:8px}.candidate-group small{color:#8b5e16}.repair-form{padding:14px;background:#f8fafc;border-radius:8px}.repair-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}.repair-columns section{display:grid;gap:4px;padding:12px;border:1px solid #e5e7eb;border-radius:8px}.repair-columns span,.repair-safety{color:#6b7280}.repair-accounts{display:grid;gap:3px;margin-top:6px;padding-top:7px;border-top:1px dashed #d8dee8}.repair-accounts span{font-size:12px;color:#374151}.repair-accounts small{color:#8b95a5}.repair-issues{margin:0;padding-left:22px;color:#8a4b08}.repair-issues.blockers{color:#b42318}.repair-safety{margin:0;font-family:monospace;font-size:12px}
</style>

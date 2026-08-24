<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { archiveSemAccount, createCustomer, fetchCustomers, setCustomerModule, updateCustomer } from '../../api/moduleAssets'

const router = useRouter()

const loading = ref(false)
const customers = ref([])
const identitySummary = ref({ checked_customers: 0, checked_accounts: 0, errors: 0, warnings: 0, healthy: true })
const visible = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', industry: '', business_desc: '', modules: ['sem'] })
const moduleLabels = { sem: 'SEM', seo: 'SEO', geo: 'GEO' }
const editingCustomer = computed(() => customers.value.find((row) => row.id === editingId.value))

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
  } catch (error) { ElMessage.error(error.message) }
}

function rebindAccount(row) {
  router.push({ path: '/onboarding', query: { tenant_id: row.id } })
}

onMounted(load)
</script>

<template>
  <div class="module-page" v-loading="loading">
    <header class="page-head">
      <div><h2>客户与模块</h2><p>平台级客户主档仅由超级管理员维护；模块内只显示已开通该模块的客户。</p></div>
      <div class="head-actions"><el-button @click="load">重新检查归属</el-button><el-button type="primary" @click="openCreate">新建客户</el-button></div>
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
          <div v-if="row.sem_accounts?.length" class="account-bindings">
            <span v-for="account in row.sem_accounts" :key="account.id">
              <span class="account-label">
                {{ account.username }} · {{ account.ucid }}
                <small>{{ account.auth_mode === 'oauth' ? 'OAuth' : '自授权' }} · {{ account.status }}</small>
              </span>
              <el-button
                v-if="account.status !== 'archived'"
                link type="danger" size="small"
                @click="archiveAccount(row, account)"
              >归档</el-button>
            </span>
          </div>
          <span v-else class="unbound">未绑定</span>
          <el-button link type="primary" size="small" @click="rebindAccount(row)">重新绑定并授权</el-button>
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
  </div>
</template>

<style scoped>
.module-page{padding:24px}.page-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px}.page-head h2{margin:0 0 7px;font-size:24px}.page-head p{margin:0;color:#6b7280}.head-actions{display:flex;gap:8px}.identity-summary{margin-bottom:16px}.account-bindings{display:grid;gap:5px;margin-bottom:6px}.account-bindings>span{display:flex;justify-content:space-between;align-items:center;gap:10px}.account-label{display:flex;flex-direction:column}.account-bindings small,.unbound{color:#8b95a5}.identity-issues{display:grid;justify-items:start;gap:5px}.identity-issues span{color:#8a4b08;font-size:12px;line-height:1.35}.identity-alert{margin-bottom:16px}
</style>

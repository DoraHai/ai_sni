<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createCustomer, fetchCustomers, setCustomerModule, updateCustomer } from '../../api/moduleAssets'

const loading = ref(false)
const customers = ref([])
const visible = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', industry: '', business_desc: '', modules: ['sem'] })
const moduleLabels = { sem: 'SEM', seo: 'SEO', geo: 'GEO' }

function moduleRow(row, code) {
  return row.modules?.find((item) => item.module_code === code)
}

async function load() {
  loading.value = true
  try { customers.value = (await fetchCustomers()).customers || [] }
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
  try {
    if (editingId.value) {
      await updateCustomer(editingId.value, { name: form.name, industry: form.industry || null, business_desc: form.business_desc || null })
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

onMounted(load)
</script>

<template>
  <div class="module-page" v-loading="loading">
    <header class="page-head">
      <div><h2>客户与模块</h2><p>平台级客户主档仅由超级管理员维护；模块内只显示已开通该模块的客户。</p></div>
      <el-button type="primary" @click="openCreate">新建客户</el-button>
    </header>
    <el-table :data="customers" border>
      <el-table-column prop="name" label="客户" min-width="180" />
      <el-table-column prop="industry" label="行业" min-width="150" />
      <el-table-column v-for="code in ['sem','seo','geo']" :key="code" :label="moduleLabels[code]" width="105" align="center">
        <template #default="{ row }"><el-tag :type="moduleRow(row, code)?.available ? 'success' : 'info'">{{ moduleRow(row, code)?.available ? '已开通' : '未开通' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">配置</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="visible" :title="editingId ? '配置客户' : '新建客户'" width="560px">
      <el-form label-width="90px">
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
.module-page{padding:24px}.page-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px}.page-head h2{margin:0 0 7px;font-size:24px}.page-head p{margin:0;color:#6b7280}
</style>

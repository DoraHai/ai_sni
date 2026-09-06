<script setup>
import { computed } from 'vue'
import { credentialKind, credentialFields } from '../utils/geoAccountCredentials'
const props = defineProps({ form: { type: Object, required: true } })
const fields = computed(() => credentialFields[credentialKind(props.form)] || [])
</script>
<template>
  <el-form-item v-if="form.id" label="更新凭据">
    <el-switch v-model="form.replace_credentials" />
    <span>关闭时保留原凭据；开启后须填写完整新凭据。</span>
  </el-form-item>
  <template v-if="!form.id || form.replace_credentials">
    <el-form-item v-if="['social_api', 'api_key'].includes(form.auth_type)" label="接入方式">
      <el-select v-model="form.provider"><el-option label="发布网关" value="gateway" /><el-option label="微信公众号原生" value="wechat_mp" /></el-select>
    </el-form-item>
    <el-form-item v-for="[key, label, required, secret] in fields" :key="key" :label="label" :required="required">
      <el-input v-model="form.credential_values[key]" :type="secret || key === 'headers' ? 'password' : 'text'" :show-password="!!secret || key === 'headers'" autocomplete="off" />
    </el-form-item>
    <p v-if="fields.length">凭据加密保存，不回显已保存的密钥。保存不代表授权或发布成功。</p>
  </template>
</template>

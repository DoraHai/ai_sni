<script setup>
import { reactive } from 'vue'
import Credentials from '../../src/components/GeoAccountCredentials.vue'
const form=reactive({auth_type:'social_api',provider:'wechat_mp',credential_values:{},replace_credentials:false})
</script>
<template><main style="max-width:700px;margin:40px auto"><h1>本地表单验证</h1><p>不发送请求，不保存凭据。</p><el-form label-width="130px"><Credentials :form="form"/></el-form></main></template>

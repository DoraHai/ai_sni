<script setup>
import GeoV2Page from '../../components/GeoV2Page.vue'
import AccountsRolesView from '../settings/AccountsRolesView.vue'
</script>

<template>
  <GeoV2Page
    tag="设置"
    title="让市场、品牌和内容团队按职责协同优化 AI 品牌表现。"
    desc="按角色管理品牌负责人、内容运营、审核人和管理者权限，确保优化动作可协作、可追踪。"
    :steps="['添加成员', '分配角色', '设置审批', '追踪协作']"
    compact
    :answer="{
      now: ['我现在怎么样？', '用现有账号与角色控制谁能生成、审核和发布内容。'],
      why: ['为什么？', '清晰分工能减少误发，也让优化动作可追踪。'],
      next: ['下一步怎么办？', '给内容运营开放 geo.content，审核人保留发布权限。'],
    }"
  >
    <AccountsRolesView />
  </GeoV2Page>
</template>

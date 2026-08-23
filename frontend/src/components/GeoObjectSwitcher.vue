<script setup>
import { useGeoObjectScope } from '../composables/useGeoObjectScope'

const {
  businesses,
  filteredUnits,
  filteredPrompts,
  businessId,
  unitId,
  promptId,
} = useGeoObjectScope()
</script>

<template>
  <section class="gv2-switcher" aria-label="业务、关键词、AI提问切换">
    <div>
      <label>业务</label>
      <el-select
        v-model="businessId"
        clearable
        filterable
        placeholder="全部业务"
        style="width: 100%"
      >
        <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
    </div>
    <div>
      <label>关键词</label>
      <el-select
        v-model="unitId"
        clearable
        filterable
        placeholder="全部关键词"
        style="width: 100%"
      >
        <el-option
          v-for="u in filteredUnits"
          :key="u.id"
          :label="u.keyword || u.name"
          :value="u.id"
        />
      </el-select>
    </div>
    <div>
      <label>AI提问</label>
      <el-select
        v-model="promptId"
        clearable
        filterable
        placeholder="全部提问"
        style="width: 100%"
      >
        <el-option
          v-for="p in filteredPrompts"
          :key="p.id"
          :label="p.question"
          :value="p.id"
        />
      </el-select>
    </div>
  </section>
</template>

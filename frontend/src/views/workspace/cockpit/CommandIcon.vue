<script setup>
defineProps({ name: { type: String, default: 'activity' } })
const paths = {
 wallet: ['M3 7h16a2 2 0 0 1 2 2v10H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h13v4','M21 11h-6v4h6'],
 pointer: ['m4 3 7 18 2-8 8-2L4 3Z','m13 13 6 6'],
 search: ['M16 16 21 21','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
 file: ['M14 2H5v20h14V7l-5-5Z','M14 2v6h5','M8 12h8M8 16h6'],
 radar: ['M20 12a8 8 0 1 1-8-8','M16 12a4 4 0 1 1-4-4','m12 12 9-9','M12 11v2'],
 eye: ['M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z','M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0'],
 spark: ['m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z'],
 shield: ['m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5l8-3Z','m8 12 3 3 5-6'],
 alert: ['m12 3 10 18H2L12 3Z','M12 9v5M12 17v.1'],
 database: ['M3 5v14c0 4 18 4 18 0V5','M21 5c0 4-18 4-18 0s18-4 18 0','M3 12c0 4 18 4 18 0'],
 activity: ['M2 12h5l3-8 4 16 3-8h5'],
 flow: ['M4 4h5v5H4zM15 15h5v5h-5z','M9 6h8v9M6 9v8h9'],
 arrow: ['M5 12h14m-5-5 5 5-5 5'],
}
</script>
<template><svg class="command-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path v-for="(path,i) in (paths[name] || paths.activity)" :key="i" :d="path" /></svg></template>
<style scoped>.command-icon{width:19px;height:19px;flex-shrink:0;vertical-align:middle}</style>

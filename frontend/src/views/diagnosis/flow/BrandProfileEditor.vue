<script setup>
import { brandFields } from '../brandProfileFields'
defineProps({ draft:Object, fields:{type:Array,default:()=>brandFields} })
defineEmits(['field'])
</script>
<template><div class="fd-editor"><label v-for="field in fields" :key="field.key"><span>{{ field.label }}<small v-if="field.required"> *</small></span><textarea v-if="field.list || field.multiline" :value="draft[field.key]" :required="field.required" rows="3" @input="$emit('field',field.key,$event.target.value)" /><input v-else :value="draft[field.key]" :required="field.required" @input="$emit('field',field.key,$event.target.value)"><small v-if="field.list">每行一项</small></label></div></template>

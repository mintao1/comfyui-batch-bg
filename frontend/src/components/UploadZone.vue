<script setup>
import { ref } from 'vue'

const props = defineProps({ multiple: { type: Boolean, default: true }, label: String, compact: Boolean })
const emit = defineEmits(['files'])
const dragging = ref(false)
const input = ref(null)

function pick(list) {
  const files = [...list].filter((f) => f.type.startsWith('image/'))
  if (files.length) emit('files', props.multiple ? files : files.slice(0, 1))
}
function onDrop(e) {
  dragging.value = false
  pick(e.dataTransfer.files)
}
function onChange(e) {
  pick(e.target.files)
  e.target.value = ''
}
</script>

<template>
  <div
    class="upload-zone"
    :class="{ dragging, compact }"
    @click="input.click()"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <input ref="input" type="file" accept="image/*" :multiple="multiple" hidden @change="onChange" />
    <div class="upload-icon">⇪</div>
    <div>{{ label || '点击或拖拽图片到这里（支持多选）' }}</div>
    <div v-if="!compact" class="muted">JPG / PNG / WEBP / BMP</div>
  </div>
</template>

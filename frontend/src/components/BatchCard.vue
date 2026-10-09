<script setup>
import { computed } from 'vue'

const props = defineProps({ batch: Object })
const emit = defineEmits(['retry', 'preview'])

const MODE_LABEL = { white: '纯色/白底', replace_image: '换背景 · 图片', replace_prompt: '换背景 · 提示词' }
const STATUS_LABEL = { queued: '排队中', running: '处理中', done: '完成', failed: '失败' }

const progress = computed(() => {
  const { done, failed } = props.batch.counts
  return Math.round(((done + failed) / props.batch.total) * 100)
})
const time = computed(() => new Date(props.batch.created_at * 1000).toLocaleTimeString())
</script>

<template>
  <section class="card batch">
    <header class="batch-head">
      <div>
        <strong>{{ MODE_LABEL[batch.options.mode] }}</strong>
        <span class="muted"> · {{ batch.total }} 张 · {{ time }}</span>
        <div v-if="batch.options.mode === 'replace_prompt'" class="muted prompt">“{{ batch.options.prompt }}”</div>
      </div>
      <div class="batch-actions">
        <span class="muted">
          完成 {{ batch.counts.done }} / 失败 {{ batch.counts.failed }} / 进行中
          {{ batch.counts.running + batch.counts.queued }}
        </span>
        <a
          class="btn small"
          :class="{ disabled: !batch.counts.done }"
          :href="batch.counts.done ? `/api/batches/${batch.id}/download` : undefined"
        >下载 ZIP</a>
      </div>
    </header>
    <div class="progress"><div class="bar" :style="{ width: progress + '%' }" /></div>

    <div class="results">
      <figure v-for="t in batch.tasks" :key="t.id" class="result" :class="t.status">
        <div class="pair">
          <img :src="t.source_url" :alt="t.filename" loading="lazy" />
          <img
            v-if="t.result_url"
            :src="t.result_url"
            :alt="t.filename + ' 结果'"
            class="clickable checker"
            @click="emit('preview', t)"
          />
          <div v-else class="placeholder">
            <span v-if="t.status === 'running'" class="spinner" />
            {{ STATUS_LABEL[t.status] }}
          </div>
        </div>
        <figcaption>
          <span class="name" :title="t.filename">{{ t.filename }}</span>
          <span class="tag" :class="t.status">{{ STATUS_LABEL[t.status] }}</span>
        </figcaption>
        <div v-if="t.error" class="error" :title="t.error">{{ t.error }}</div>
        <div class="row-actions">
          <a v-if="t.result_url" class="link" :href="t.result_url + '?download=true'">下载</a>
          <button v-if="t.status === 'failed'" class="link" @click="emit('retry', t)">重试</button>
        </div>
      </figure>
    </div>
  </section>
</template>

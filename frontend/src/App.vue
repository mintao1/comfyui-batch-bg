<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api } from './api'
import UploadZone from './components/UploadZone.vue'
import BatchCard from './components/BatchCard.vue'

const health = ref(null)
const images = ref([]) // 已上传的待处理图片
const selected = ref(new Set())
const background = ref(null) // 换背景用的背景图
const batches = ref([])
const uploading = ref(false)
const submitting = ref(false)
const message = ref(null)
const preview = ref(null)

const COLOR_PRESETS = ['#FFFFFF', '#F5F5F5', '#000000', '#E8F0FE', '#FDECEC', '#EAF7EE']
const PROMPT_PRESETS = [
  'clean minimalist studio background, soft light, product photography',
  'marble tabletop, bright kitchen, soft daylight, shallow depth of field',
  'wooden table in a cozy cafe, warm light, bokeh',
  'beach at sunset, golden hour, soft focus background',
]

const form = reactive({
  mode: 'white',
  bg_color: '#FFFFFF',
  prompt: PROMPT_PRESETS[0],
  negative_prompt: 'text, watermark, blurry, low quality, person',
  seed: -1,
  steps: 25,
  cfg: 7,
})

const selectedCount = computed(() => selected.value.size)
const canSubmit = computed(() => {
  if (!selectedCount.value || submitting.value) return false
  if (form.mode === 'replace_image') return !!background.value
  if (form.mode === 'replace_prompt') return !!form.prompt.trim()
  return true
})

function notify(text, type = 'info') {
  message.value = { text, type }
  setTimeout(() => (message.value = null), 4000)
}

async function onFiles(files) {
  uploading.value = true
  try {
    const res = await api.upload(files)
    images.value.push(...res.uploaded)
    const next = new Set(selected.value)
    res.uploaded.forEach((u) => next.add(u.id))
    selected.value = next
    if (res.errors.length) notify(res.errors.map((e) => `${e.filename}: ${e.error}`).join('；'), 'error')
    else notify(`已上传 ${res.uploaded.length} 张图片`)
  } catch (e) {
    notify(`上传失败：${e.message}`, 'error')
  } finally {
    uploading.value = false
  }
}

async function onBackground(files) {
  try {
    const res = await api.upload(files)
    if (res.uploaded[0]) background.value = res.uploaded[0]
    if (res.errors.length) notify(res.errors[0].error, 'error')
  } catch (e) {
    notify(`背景上传失败：${e.message}`, 'error')
  }
}

function toggle(id) {
  const next = new Set(selected.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selected.value = next
}
function selectAll() {
  selected.value = new Set(images.value.map((i) => i.id))
}
function clearSelection() {
  selected.value = new Set()
}
function removeSelected() {
  images.value = images.value.filter((i) => !selected.value.has(i.id))
  clearSelection()
}

async function submit() {
  submitting.value = true
  try {
    const payload = {
      image_ids: images.value.filter((i) => selected.value.has(i.id)).map((i) => i.id),
      mode: form.mode,
    }
    if (form.mode === 'white') payload.bg_color = form.bg_color
    if (form.mode === 'replace_image') payload.background_id = background.value.id
    if (form.mode === 'replace_prompt') {
      Object.assign(payload, {
        prompt: form.prompt,
        negative_prompt: form.negative_prompt,
        seed: Number(form.seed),
        steps: Number(form.steps),
        cfg: Number(form.cfg),
      })
    }
    const batch = await api.createBatch(payload)
    batches.value.unshift(batch)
    notify(`已提交 ${batch.total} 张图片`)
    schedulePoll(300)
  } catch (e) {
    notify(`提交失败：${e.message}`, 'error')
  } finally {
    submitting.value = false
  }
}

async function retry(task) {
  try {
    await api.retry(task.id)
    await refresh()
  } catch (e) {
    notify(e.message, 'error')
  }
}

let timer = null
async function refresh() {
  try {
    batches.value = await api.listBatches()
  } catch {}
  schedulePoll()
}
function schedulePoll(delay = 1500) {
  clearTimeout(timer)
  if (batches.value.some((b) => !b.finished) || delay < 1500) timer = setTimeout(refresh, delay)
}

async function checkHealth() {
  try {
    health.value = await api.health()
  } catch (e) {
    health.value = { ok: false, error: e.message }
  }
}

let healthTimer = null
onMounted(() => {
  checkHealth()
  refresh()
  healthTimer = setInterval(checkHealth, 15000)
})
onUnmounted(() => {
  clearTimeout(timer)
  clearInterval(healthTimer)
})
</script>

<template>
  <header class="topbar">
    <h1>ComfyUI 批量白底图 / 换背景</h1>
    <div class="status" :class="health?.ok ? 'ok' : 'bad'" :title="health?.error || health?.comfyui">
      <span class="dot" />
      {{ health == null ? '检测中…' : health.ok ? 'ComfyUI 已连接' : 'ComfyUI 未连接' }}
    </div>
  </header>

  <main class="layout">
    <section class="card gallery-card">
      <div class="section-head">
        <h2>1. 上传图片</h2>
        <div v-if="images.length" class="toolbar">
          <span class="muted">已选 {{ selectedCount }} / {{ images.length }}</span>
          <button class="link" @click="selectAll">全选</button>
          <button class="link" @click="clearSelection">取消选择</button>
          <button class="link danger" :disabled="!selectedCount" @click="removeSelected">移除所选</button>
        </div>
      </div>
      <UploadZone :label="uploading ? '上传中…' : undefined" @files="onFiles" />
      <div v-if="images.length" class="gallery">
        <div
          v-for="img in images"
          :key="img.id"
          class="thumb"
          :class="{ selected: selected.has(img.id) }"
          @click="toggle(img.id)"
        >
          <img :src="img.url" :alt="img.filename" loading="lazy" />
          <span class="check">✓</span>
          <span class="thumb-name" :title="img.filename">{{ img.filename }}</span>
          <span class="thumb-size">{{ img.width }}×{{ img.height }}</span>
        </div>
      </div>
    </section>

    <aside class="card settings">
      <h2>2. 处理方式</h2>
      <div class="tabs">
        <button :class="{ active: form.mode === 'white' }" @click="form.mode = 'white'">白底图</button>
        <button :class="{ active: form.mode === 'replace_image' }" @click="form.mode = 'replace_image'">
          换背景·图片
        </button>
        <button :class="{ active: form.mode === 'replace_prompt' }" @click="form.mode = 'replace_prompt'">
          AI 生成背景
        </button>
      </div>

      <div v-if="form.mode === 'white'" class="field">
        <label>背景颜色</label>
        <div class="colors">
          <button
            v-for="c in COLOR_PRESETS"
            :key="c"
            class="swatch"
            :class="{ active: form.bg_color.toUpperCase() === c }"
            :style="{ background: c }"
            :title="c"
            @click="form.bg_color = c"
          />
          <input v-model="form.bg_color" type="color" />
          <code>{{ form.bg_color.toUpperCase() }}</code>
        </div>
        <p class="muted">自动抠出主体，合成到纯色背景上，尺寸与原图一致。</p>
      </div>

      <div v-else-if="form.mode === 'replace_image'" class="field">
        <label>背景图片</label>
        <div v-if="background" class="bg-preview">
          <img :src="background.url" alt="背景" />
          <button class="link danger" @click="background = null">更换</button>
        </div>
        <UploadZone v-else compact :multiple="false" label="上传一张背景图" @files="onBackground" />
        <p class="muted">背景会按原图尺寸居中缩放裁剪，再与抠出的主体合成。</p>
      </div>

      <template v-else>
        <div class="field">
          <label>背景描述（英文效果更好）</label>
          <textarea v-model="form.prompt" rows="3" />
          <div class="chips">
            <button v-for="p in PROMPT_PRESETS" :key="p" class="chip" :title="p" @click="form.prompt = p">
              {{ p.split(',')[0] }}
            </button>
          </div>
        </div>
        <div class="field">
          <label>反向提示词</label>
          <input v-model="form.negative_prompt" type="text" />
        </div>
        <div class="grid3">
          <div class="field">
            <label>Seed（-1 随机）</label>
            <input v-model.number="form.seed" type="number" />
          </div>
          <div class="field">
            <label>步数</label>
            <input v-model.number="form.steps" type="number" min="1" max="150" />
          </div>
          <div class="field">
            <label>CFG</label>
            <input v-model.number="form.cfg" type="number" step="0.5" min="0" max="30" />
          </div>
        </div>
      </template>

      <button class="btn primary block" :disabled="!canSubmit" @click="submit">
        {{ submitting ? '提交中…' : `开始处理（${selectedCount} 张）` }}
      </button>
    </aside>
  </main>

  <section class="batches">
    <h2>3. 处理结果</h2>
    <p v-if="!batches.length" class="muted">还没有任务。上传图片、选择处理方式后点击“开始处理”。</p>
    <BatchCard v-for="b in batches" :key="b.id" :batch="b" @retry="retry" @preview="preview = $event" />
  </section>

  <div v-if="preview" class="modal" @click="preview = null">
    <div class="modal-body" @click.stop>
      <div class="compare">
        <figure><img :src="preview.source_url" /><figcaption>原图</figcaption></figure>
        <figure><img :src="preview.result_url" class="checker" /><figcaption>结果</figcaption></figure>
      </div>
      <div class="modal-actions">
        <a class="btn primary" :href="preview.result_url + '?download=true'">下载结果</a>
        <button class="btn" @click="preview = null">关闭</button>
      </div>
    </div>
  </div>

  <div v-if="message" class="toast" :class="message.type">{{ message.text }}</div>
</template>

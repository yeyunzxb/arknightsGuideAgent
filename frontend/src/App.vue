<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowUp, Check, ChevronDown, Database, FileText, KeyRound, Layers, Menu, MessageSquare, Moon, Plus, RefreshCw, Search, Settings2, ShieldCheck, Square, Sun, Trash2, Upload, X } from 'lucide-vue-next'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api, streamChat } from './api'
import logoUrl from './assets/rhodes-island.png'

const page = ref('chat'), modal = ref(false), key = ref(''), model = ref('')
const models = ref([])
const verified = ref(false), verifying = ref(false), settingsError = ref(''), toast = ref('')
const question = ref(''), messages = ref([]), busy = ref(false), connected = ref(false), feed = ref(null)
const knowledge = ref({ documents: 0, chunks: 0, files: [], errors: [] }), indexing = ref(false), importing = ref(false), filter = ref('')
const inputFile = ref(null), topK = ref(4), sessions = ref([]), activeSession = ref(crypto.randomUUID())
const theme = ref(document.documentElement.dataset.theme || 'light'), sidebarOpen = ref(false), settingsDialog = ref(null)
const mobileViewport = matchMedia('(max-width: 760px)'), isMobile = ref(mobileViewport.matches)
let controller, toastTimer, modelController, verificationVersion = 0
let previousFocus
const hasVerifiedModel = computed(() => verified.value && !!key.value.trim() && models.value.some(item => item.id === model.value))
watch(key, () => {
  // 密钥变化后，旧列表和仍在途中的验证结果都不再适用于当前密钥。
  verificationVersion++
  modelController?.abort()
  models.value = []; model.value = ''; verified.value = false; verifying.value = false; settingsError.value = ''
}, { flush: 'sync' })
function handleViewportChange(event) { isMobile.value = event.matches; if (!event.matches) sidebarOpen.value = false }
function handleGlobalKeydown(event) {
  if (event.key === 'Escape') { modal.value = false; sidebarOpen.value = false }
}
function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  document.documentElement.dataset.theme = theme.value
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.value === 'dark' ? '#1b2320' : '#f8f9f7')
  try { localStorage.setItem('prts-theme', theme.value) } catch {}
}
function navigate(target) { page.value = target; sidebarOpen.value = false; if (target === 'knowledge') loadKnowledge() }
function safeUrl(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null } catch { return null } }
function trapDialogFocus(event) {
  if (event.key === 'Escape') { modal.value = false; return }
  if (event.key !== 'Tab') return
  const items = [...settingsDialog.value.querySelectorAll('button:not(:disabled), input, select, a[href]')]
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
watch(modal, async open => {
  if (open) { previousFocus = document.activeElement; await nextTick(); settingsDialog.value?.querySelector('input')?.focus() }
  else { await nextTick(); previousFocus?.focus() }
})
watch(sidebarOpen, async open => {
  await nextTick()
  if (open) document.querySelector('#sidebar nav button')?.focus()
  else if (isMobile.value && !modal.value) document.querySelector('.mobile-menu')?.focus()
})
const files = computed(() => knowledge.value.files.filter(f => `${f.title} ${f.filename} ${f.tags.join(' ')}`.includes(filter.value)))
const render = text => DOMPurify.sanitize(marked.parse(text || '', { breaks: true }))
function notify(text) { toast.value = text; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 4500) }
async function loadKnowledge() {
  try { knowledge.value = await (await api('/knowledge')).json(); connected.value = true }
  catch { connected.value = false; notify('后端连接失败，请确认已运行启动脚本。') }
}
function persist() {
  const existing = sessions.value.find(s => s.id === activeSession.value)
  const data = { id: activeSession.value, title: messages.value.find(m => m.role === 'user')?.content.slice(0, 24) || '新对话', messages: JSON.parse(JSON.stringify(messages.value)) }
  if (existing) Object.assign(existing, data)
  else sessions.value.unshift(data)
  sessions.value = sessions.value.slice(0, 20)
  try { localStorage.setItem('prts-chats', JSON.stringify(sessions.value)) } catch { notify('浏览器存储已满，本次对话仅保留在内存。') }
}
function newChat() { if (busy.value) return; messages.value = []; activeSession.value = crypto.randomUUID(); navigate('chat') }
function openChat(session) { if (busy.value) return; activeSession.value = session.id; messages.value = JSON.parse(JSON.stringify(session.messages)); navigate('chat'); scroll() }
function deleteChat(id) {
  if (busy.value) return
  sessions.value = sessions.value.filter(s => s.id !== id)
  try { localStorage.setItem('prts-chats', JSON.stringify(sessions.value)) } catch {}
  if (activeSession.value === id) newChat()
}
async function scroll() { await nextTick(); if (feed.value) feed.value.scrollTop = feed.value.scrollHeight }
async function send(text = question.value) {
  if (busy.value || !text.trim()) return
  if (!hasVerifiedModel.value) {
    modal.value = true
    settingsError.value = key.value.trim() ? '请先验证 API Key，获取并选择可用模型后再开始对话。' : '请先填写 DeepSeek API Key，并验证获取可用模型。'
    return
  }
  if (text.trim().length > 2000) return notify('问题请控制在 2000 字以内。')
  const history = messages.value.filter(m => m.content && !m.error && !m.incomplete).map(m => ({ role: m.role, content: m.content.slice(0, 8000) })).slice(-12)
  messages.value.push({ role: 'user', content: text.trim() })
  const answer = { role: 'assistant', content: '', sources: [], incomplete: true }
  messages.value.push(answer)
  const index = messages.value.length - 1
  question.value = ''; busy.value = true; controller = new AbortController(); scroll()
  try {
    await streamChat({ api_key: key.value.trim(), model: model.value, question: text.trim(), history, top_k: Number(topK.value) }, (name, data) => {
      const target = messages.value[index]
      if (name === 'sources') target.sources = data
      if (name === 'token') { target.content += data; scroll() }
      if (name === 'error') target.error = data.message
      if (name === 'done') {
        target.incomplete = false; target.model = data.model
      }
    }, controller.signal)
  } catch (error) {
    messages.value[index].error = error.name === 'AbortError' ? '已停止生成' : error.message
  } finally { busy.value = false; persist(); scroll() }
}
async function verify() {
  if (!key.value.trim() || verifying.value) return
  const selectedModel = model.value, currentKey = key.value.trim(), version = ++verificationVersion
  modelController?.abort()
  modelController = new AbortController()
  settingsError.value = ''; verifying.value = true; verified.value = false; models.value = []; model.value = ''
  try {
    const data = await (await api('/models', { api_key: currentKey }, modelController.signal)).json()
    if (version !== verificationVersion || key.value.trim() !== currentKey) return
    if (!Array.isArray(data.models) || !data.models.length) throw new Error('此密钥下没有可用的 DeepSeek 模型。')
    models.value = data.models
    model.value = data.models.some(m => m.id === selectedModel) ? selectedModel : data.models[0].id
    verified.value = true; notify('连接成功，已同步可用模型。')
  } catch (error) { if (version === verificationVersion && error.name !== 'AbortError') settingsError.value = error.message }
  finally { if (version === verificationVersion) verifying.value = false }
}
async function reindex() {
  indexing.value = true
  try { knowledge.value = await (await api('/knowledge/reindex', {})).json(); notify('索引已重建。') }
  catch (error) { notify(error.message) } finally { indexing.value = false }
}
async function upload(event) {
  const selected = [...(event.target.files || [])]; importing.value = true
  let count = 0
  try {
    for (const file of selected) {
      if (file.size > 1000000) throw new Error(`${file.name} 超过 1 MB`)
      knowledge.value = await (await api('/knowledge', { filename: file.name, content: await file.text() })).json(); count++
    }
    if (count) notify(`已导入 ${count} 份资料并更新索引。`)
  } catch (error) { notify(`已导入 ${count} 份。${error.message}`) }
  finally { event.target.value = ''; importing.value = false }
}
function downloadTemplate() {
  const content = '---\ntitle: "干员或机制名称"\ncategory: "干员"\ntags: ["名称", "别名"]\nsource: "资料来源链接或出处"\nupdated: "2026-11-05"\nserver: "国服"\n---\n\n# 干员或机制名称\n\n## 概述\n填写已经核实的内容。\n\n## 详细说明\n标明精英化阶段、技能等级、模组等级等适用条件。\n\n## 限制与注意事项\n记录版本变化、例外和需要进一步核实的内容。\n'
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = '知识库模板.md'; link.click(); URL.revokeObjectURL(url)
}
onMounted(() => {
  document.addEventListener('keydown', handleGlobalKeydown)
  mobileViewport.addEventListener('change', handleViewportChange)
  loadKnowledge()
  try { const saved = JSON.parse(localStorage.getItem('prts-chats') || '[]'); if (Array.isArray(saved)) sessions.value = saved.filter(s => typeof s.id === 'string' && typeof s.title === 'string' && Array.isArray(s.messages)).slice(0, 20) } catch {}
})
onBeforeUnmount(() => { controller?.abort(); modelController?.abort(); clearTimeout(toastTimer); document.removeEventListener('keydown', handleGlobalKeydown); mobileViewport.removeEventListener('change', handleViewportChange) })
</script>

<template>
  <div class="workspace">
    <button v-if="sidebarOpen" class="sidebar-scrim" aria-label="关闭导航" @click="sidebarOpen = false"></button>
    <aside id="sidebar" class="sidebar" :class="{ 'is-open': sidebarOpen }" :inert="modal || (isMobile && !sidebarOpen)" aria-label="主导航">
      <a class="brand" href="#" aria-label="PRTS 首页" @click.prevent="newChat">
        <img :src="logoUrl" alt="罗德岛标志" class="brand-logo"/>
        <span class="brand-name">PRTS<small>明日方舟知识助手</small></span>
      </a>
      <button class="new-chat" @click="newChat" :disabled="busy"><Plus :size="18"/> 新建对话</button>
      <nav aria-label="功能导航">
        <button :class="{ selected: page === 'chat' }" :aria-current="page === 'chat' ? 'page' : undefined" @click="navigate('chat')"><MessageSquare :size="18"/> 智能问答</button>
        <button :class="{ selected: page === 'knowledge' }" :aria-current="page === 'knowledge' ? 'page' : undefined" @click="navigate('knowledge')"><Database :size="18"/> 知识库 <span>{{ knowledge.documents }}</span></button>
      </nav>
      <div class="history-heading">最近对话</div>
      <div class="history">
        <p v-if="!sessions.length" class="no-history">你的对话会保存在这里</p>
        <div v-for="s in sessions" :key="s.id" class="history-row" :class="{ active: s.id === activeSession }">
          <button @click="openChat(s)" :disabled="busy" :title="s.title"><MessageSquare :size="15"/><span>{{ s.title }}</span></button>
          <button :disabled="busy" @click="deleteChat(s.id)" :aria-label="`删除对话：${s.title}`"><Trash2 :size="14"/></button>
        </div>
      </div>
      <div class="sidebar-bottom">
        <button class="settings-button" @click="modal = true; sidebarOpen = false" aria-label="博士 · 连接设置">
          <span class="avatar">博</span><span class="profile-name">博士<small>{{ verified ? 'DeepSeek 已连接' : key ? '已填写密钥' : '连接你的 DeepSeek' }}</small></span><Settings2 :size="18"/>
        </button>
      </div>
    </aside>

    <main :inert="modal || sidebarOpen">
      <header class="topbar">
        <button class="mobile-menu icon-button" @click="sidebarOpen = !sidebarOpen" aria-label="打开导航" aria-controls="sidebar" :aria-expanded="sidebarOpen"><Menu :size="21"/></button>
        <div class="topbar-right">
          <span class="connection" :class="{ offline: !connected }"><i></i>{{ connected ? '本地服务已连接' : '本地服务未连接' }}</span>
          <button class="theme-toggle icon-button" @click="toggleTheme" :aria-label="theme === 'light' ? '切换至深色模式' : '切换至浅色模式'" :title="theme === 'light' ? '切换至深色模式' : '切换至浅色模式'"><Moon v-if="theme === 'light'" :size="18"/><Sun v-else :size="18"/></button>
        </div>
      </header>

      <section v-if="page === 'chat'" class="chat-stage" :class="{ 'is-empty': !messages.length }" aria-label="智能问答">
        <div v-if="!messages.length" class="welcome">
          <img :src="logoUrl" alt="罗德岛标志" class="welcome-logo"/>
          <h1>欢迎回来，博士。</h1>
          <p>关于泰拉的疑问，从这里开始。</p>
        </div>
        <div v-else ref="feed" class="message-feed" aria-live="polite" aria-relevant="additions text">
          <article v-for="(m, index) in messages" :key="index" class="message" :class="m.role">
            <div class="message-avatar"><span v-if="m.role === 'user'">博</span><img v-else :src="logoUrl" alt="PRTS"/></div>
            <div class="message-body">
              <div class="message-name">{{ m.role === 'user' ? '博士' : 'PRTS' }}</div>
              <div v-if="m.role === 'user'" class="user-content">{{ m.content }}</div>
              <div v-else class="prose" v-html="render(m.content)"></div>
              <div v-if="busy && index === messages.length - 1 && !m.content" class="loading-text"><span class="loading-dots">•••</span> 正在查找资料并思考</div>
              <p v-if="m.error" class="inline-error" role="alert">{{ m.error }}</p>
              <details v-if="m.sources?.length" class="sources">
                <summary><FileText :size="15"/> 参考资料 · {{ m.sources.length }} <ChevronDown :size="14"/></summary>
                <div v-for="s in m.sources" :key="s.citation" class="source-item">
                  <strong>[{{ s.citation }}] {{ s.title }}</strong>
                  <small>{{ s.server }} · 更新于 {{ s.updated }}</small><p>{{ s.text }}</p>
                  <a v-if="safeUrl(s.source)" :href="safeUrl(s.source)" target="_blank" rel="noopener noreferrer">查看原文 ↗</a><span v-else class="source-origin">来源：{{ s.source }}</span>
                </div>
                <p class="source-hint">请结合资料原文与适用版本核实回答。</p>
              </details>
            </div>
          </article>
        </div>

        <div class="composer-wrap">
          <form class="composer" @submit.prevent="send()">
            <textarea v-model="question" aria-label="输入问题" placeholder="向 PRTS 提问…" :rows="messages.length ? 2 : 3" maxlength="2000" @keydown.enter.exact="e => { if (!e.isComposing) { e.preventDefault(); send() } }"></textarea>
            <div class="composer-bottom">
              <div class="model-slot"><button v-if="hasVerifiedModel" class="model-pill" type="button" @click="modal = true" aria-label="选择模型和连接设置"><span class="model-dot"></span>{{ model }}<ChevronDown :size="13"/></button></div>
              <div class="send-actions"><span class="enter-tip">Enter 发送</span><button v-if="busy" type="button" class="send-button" @click="controller?.abort()" aria-label="停止生成"><Square :size="16"/></button><button v-else class="send-button" :disabled="!question.trim()" aria-label="发送问题"><ArrowUp :size="20"/></button></div>
            </div>
          </form>
          <div v-if="!key" class="key-banner"><KeyRound :size="13"/><span>使用自己的 DeepSeek API Key</span><button @click="modal = true">配置连接 ↗</button></div>
          <p v-else class="footer-note">回答基于本地知识库，请结合参考资料核实。</p>
        </div>
      </section>

      <section v-else-if="page === 'knowledge'" class="content-page">
        <div class="page-heading"><div><h1>知识库</h1><p>收藏资料，让每个回答都有据可循。</p></div><button class="primary" :disabled="importing" @click="inputFile.click()"><Upload :size="17"/>{{ importing ? '导入中…' : '导入资料' }}</button><input ref="inputFile" type="file" accept=".md" multiple hidden @change="upload"/></div>
        <div class="stats-grid"><div><Database :size="20"/><strong>{{ knowledge.documents }}</strong><span>资料文档</span></div><div><Layers :size="20"/><strong>{{ knowledge.chunks }}</strong><span>可检索片段</span></div><div><ShieldCheck :size="20"/><strong>本地存储</strong><span>资料保存在你的设备上</span></div></div>
        <div class="knowledge-guide"><FileText :size="23"/><div><h3>添加你的资料</h3><p>下载模板并填写内容，导入 Markdown 文件即可使用。修改本地资料后，点击“更新索引”使其生效。</p></div><button @click="downloadTemplate">下载模板 ↗</button></div>
        <div class="file-toolbar"><label><Search :size="17"/><input v-model="filter" aria-label="搜索资料" placeholder="搜索标题、文件或标签"/></label><button :disabled="indexing" @click="reindex"><RefreshCw :size="16" :class="{ spinning: indexing }"/>{{ indexing ? '更新中…' : '更新索引' }}</button></div>
        <div class="file-list"><div v-for="f in files" :key="f.filename" class="file-row"><div class="file-icon"><FileText :size="20"/></div><div class="file-info"><strong>{{ f.title }}</strong><small>{{ f.server }} · 更新于 {{ f.updated }}</small></div><span class="category">{{ f.category }}</span><span class="file-size">{{ f.characters.toLocaleString() }} 字</span></div></div>
        <div v-if="!files.length" class="empty-state"><Database :size="28"/><p>{{ filter ? '没有找到匹配的资料，换个关键词试试。' : '还没有资料，导入第一份文档开始使用。' }}</p></div>
        <div v-for="e in knowledge.errors" :key="e.filename" class="inline-error">{{ e.filename }}：{{ e.error }}</div>
      </section>
    </main>

    <div v-if="modal" class="modal-overlay" @click.self="modal = false" @keydown="trapDialogFocus">
      <section ref="settingsDialog" class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <button class="modal-close icon-button" @click="modal = false" aria-label="关闭设置"><X :size="20"/></button>
        <div class="modal-icon"><KeyRound :size="23"/></div><h2 id="settings-title">连接 DeepSeek</h2><p class="modal-description">使用你的 API Key，选择模型后即可开始对话。</p>
        <label class="field">DeepSeek API Key<input v-model="key" type="password" placeholder="sk-…" autocomplete="off" spellcheck="false"/></label>
        <div class="key-help"><span>仅在当前页面保留，刷新后清除。</span><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer">获取密钥 ↗</a></div>
        <button class="verify-button" :disabled="!key.trim() || verifying" @click="verify"><Check v-if="verified" :size="16"/><RefreshCw v-else :size="16" :class="{ spinning: verifying }"/>{{ verifying ? '正在连接…' : verified ? '已连接 · 刷新模型列表' : '验证连接并获取模型' }}</button>
        <label class="field">回答模型<select v-model="model" aria-label="回答模型" :disabled="!verified || !models.length || verifying"><option disabled value="">{{ verifying ? '正在获取模型列表…' : '请先验证 API Key 并获取模型' }}</option><option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }} ({{ m.id }})</option></select></label>
        <label class="field">参考资料数量<select v-model="topK"><option :value="2">2 个 · 精简</option><option :value="4">4 个 · 推荐</option><option :value="6">6 个 · 更多上下文</option></select></label>
        <p v-if="settingsError" class="inline-error" role="alert">{{ settingsError }}</p>
        <div class="privacy-note"><ShieldCheck :size="17"/><span>密钥仅用于连接 DeepSeek 官方接口。提问、最近对话和相关资料会随请求发送。</span></div>
        <button class="primary full" @click="modal = false">完成配置</button>
      </section>
    </div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

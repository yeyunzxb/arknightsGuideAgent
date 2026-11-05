<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ArrowUp, BookOpen, Check, ChevronDown, Database, FileText, KeyRound, Layers, MessageSquare, Plus, RefreshCw, Search, Settings2, ShieldCheck, Square, Terminal, Trash2, Upload, X, Zap } from 'lucide-vue-next'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api, streamChat } from './api'

const page = ref('chat'), modal = ref(false), key = ref(''), model = ref('deepseek-flash')
const models = ref([{ id: 'deepseek-flash', name: 'DeepSeek Flash' }, { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro' }])
const verified = ref(false), verifying = ref(false), settingsError = ref(''), toast = ref('')
const question = ref(''), messages = ref([]), busy = ref(false), connected = ref(false), feed = ref(null)
const knowledge = ref({ documents: 0, chunks: 0, files: [], errors: [] }), indexing = ref(false), importing = ref(false), filter = ref('')
const inputFile = ref(null), topK = ref(4), sessions = ref([]), activeSession = ref(crypto.randomUUID())
let controller, toastTimer
const examples = [
  { tag: 'MECHANICS', title: '物理伤害和法术伤害有什么区别？', desc: '从基础机制开始理解战斗', icon: ShieldCheck },
  { tag: 'DEVELOPMENT', title: '新手应该怎样安排干员养成？', desc: '建立自己的养成优先级', icon: Layers },
  { tag: 'KNOWLEDGE', title: '这个知识库有哪些资料？', desc: '了解资料范围与使用方式', icon: BookOpen },
]
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
function newChat() { if (busy.value) return; messages.value = []; activeSession.value = crypto.randomUUID(); page.value = 'chat' }
function openChat(session) { if (busy.value) return; activeSession.value = session.id; messages.value = JSON.parse(JSON.stringify(session.messages)); page.value = 'chat' }
function deleteChat(id) {
  if (busy.value) return
  sessions.value = sessions.value.filter(s => s.id !== id)
  try { localStorage.setItem('prts-chats', JSON.stringify(sessions.value)) } catch {}
  if (activeSession.value === id) newChat()
}
async function scroll() { await nextTick(); if (feed.value) feed.value.scrollTop = feed.value.scrollHeight }
async function send(text = question.value) {
  if (busy.value || !text.trim()) return
  if (!key.value.trim()) { modal.value = true; settingsError.value = '先填写 DeepSeek API Key，即可开始对话。'; return }
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
        // 无候选拒答在本地完成，不能用它证明密钥已经过验证。
        if (!data.refused) { verified.value = true; settingsError.value = '' }
      }
    }, controller.signal)
  } catch (error) {
    messages.value[index].error = error.name === 'AbortError' ? '已停止生成' : error.message
  } finally { busy.value = false; persist(); scroll() }
}
async function verify() {
  settingsError.value = ''; verifying.value = true
  try {
    const data = await (await api('/models', { api_key: key.value.trim() })).json()
    if (!data.models.length) throw new Error('此密钥下没有可用的 DeepSeek 模型。')
    models.value = data.models; if (!data.models.some(m => m.id === model.value)) model.value = data.models[0].id
    verified.value = true; notify('连接成功，已同步可用模型。')
  } catch (error) { settingsError.value = error.message }
  finally { verifying.value = false }
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
  loadKnowledge()
  try { const saved = JSON.parse(localStorage.getItem('prts-chats') || '[]'); if (Array.isArray(saved)) sessions.value = saved.filter(s => typeof s.id === 'string' && typeof s.title === 'string' && Array.isArray(s.messages)).slice(0, 20) } catch {}
})
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="newChat"><div class="brand-symbol">△<span>‖</span></div><div>PRTS<span>RHODES ISLAND / TERMINAL</span></div></a>
      <div class="workspace-label">博士的工作空间 <span>LOCAL</span></div>
      <button class="new-chat" @click="newChat" :disabled="busy"><Plus :size="17"/> 新建对话 <kbd>＋</kbd></button>
      <nav><button :class="{ selected: page === 'chat' }" @click="page = 'chat'"><MessageSquare :size="17"/> 智能问答 <span class="nav-dot"></span></button><button :class="{ selected: page === 'knowledge' }" @click="page = 'knowledge'; loadKnowledge()"><Database :size="17"/> 知识库 <span>{{ knowledge.documents }}</span></button><button :class="{ selected: page === 'learn' }" @click="page = 'learn'"><BookOpen :size="17"/> 学习手册 <span>↗</span></button></nav>
      <div class="history-heading">最近对话 <span>{{ sessions.length.toString().padStart(2, '0') }}</span></div>
      <div class="history"><div v-if="!sessions.length" class="no-history">从一个问题开始，<br>探索你的泰拉资料库。</div><div v-for="s in sessions" :key="s.id" class="history-row" :class="{ active: s.id === activeSession }"><button @click="openChat(s)" :disabled="busy"><MessageSquare :size="14"/><span>{{ s.title }}</span></button><button :disabled="busy" @click="deleteChat(s.id)" aria-label="删除对话"><Trash2 :size="13"/></button></div></div>
      <div class="sidebar-bottom"><div class="local-note"><ShieldCheck :size="17"/><div>本地知识，专属终端<small>无需登录 · 密钥仅存于当前页面</small></div></div><button class="settings-button" @click="modal = true"><div class="avatar">D</div><div>Doctor<small>{{ verified ? 'DeepSeek 已连接' : key ? '密钥已填写 · 未验证' : '尚未配置 API Key' }}</small></div><Settings2 :size="17"/></button></div>
    </aside>

    <main>
      <header class="topbar"><div><span class="breadcrumb">工作空间</span><span class="slash">/</span>{{ page === 'chat' ? '智能问答' : page === 'knowledge' ? '知识库' : '学习手册' }}</div><div class="topbar-right"><span class="connection" :class="{ offline: !connected }"><i></i>{{ connected ? '本地服务在线' : '服务未连接' }}</span><span class="version">v1.0</span></div></header>

      <template v-if="page === 'chat'">
        <div class="chat-toolbar"><div class="terminal-label"><Terminal :size="15"/> RAG CONSOLE <span> / 01</span></div><button class="model-pill" @click="modal = true"><Zap :size="14"/><span>{{ model }}</span><ChevronDown :size="13"/></button></div>
        <div v-if="!messages.length" class="welcome">
          <div class="eyebrow"><span></span> RHODES ISLAND INTELLIGENCE SYSTEM</div>
          <div class="welcome-mark" aria-hidden="true"><div class="mark-triangle">△</div><div class="mark-lines">|||</div><span>PRTS</span></div>
          <h1>欢迎回来，<span>博士。</span></h1>
          <p class="welcome-subtitle">连接知识，探索泰拉。<br>你的明日方舟知识助手已就绪。</p>
          <div class="capabilities"><span><Database :size="13"/> 本地知识检索</span><span><FileText :size="13"/> 回答来源可追溯</span><span><Zap :size="13"/> DeepSeek 驱动</span></div>
          <div class="suggestion-label">从这里开始 <span>试试问我</span></div>
          <div class="suggestions"><button v-for="e in examples" :key="e.tag" @click="send(e.title)"><div><component :is="e.icon" :size="19"/><span>{{ e.tag }}</span><span class="card-arrow">↗</span></div><h3>{{ e.title }}</h3><p>{{ e.desc }}</p></button></div>
          <div class="corpus-note"><span class="tiny-dot"></span> 当前知识库收录 {{ knowledge.documents }} 份资料 · {{ knowledge.chunks }} 个检索片段 <button @click="page = 'knowledge'">管理知识库 →</button></div>
        </div>
        <div v-else ref="feed" class="message-feed" aria-live="polite">
          <article v-for="(m, index) in messages" :key="index" class="message" :class="m.role">
            <div class="message-avatar">{{ m.role === 'user' ? 'D' : '△' }}</div><div class="message-body"><div class="message-name">{{ m.role === 'user' ? 'Doctor' : 'PRTS' }} <span v-if="m.role === 'assistant'">知识库助手</span></div><div v-if="m.role === 'user'" class="user-content">{{ m.content }}</div><div v-else class="prose" v-html="render(m.content)"></div><div v-if="busy && index === messages.length - 1 && !m.content" class="loading-text">正在检索资料并等待模型响应<span>•••</span></div><p v-if="m.error" class="inline-error">{{ m.error }}</p><details v-if="m.sources?.length" class="sources"><summary><FileText :size="14"/> 检索参考 · {{ m.sources.length }} 个片段 <ChevronDown :size="13"/></summary><div v-for="s in m.sources" :key="s.citation" class="source-item"><strong>[{{ s.citation }}] {{ s.title }}</strong><small>{{ s.filename }}#块{{ s.chunk_id }} · {{ s.server }} · {{ s.updated }} · 相似度 {{ s.score }}</small><p>{{ s.text }}</p><span class="source-origin">来源：{{ s.source }}</span></div><p class="source-hint">这些片段实际传给了模型；相似度不是答案正确率，请核对原文。</p></details></div>
          </article>
        </div>
        <div class="composer-wrap"><div v-if="!key" class="key-banner"><KeyRound :size="14"/><span>接入你的 DeepSeek，开启第一段对话</span><button @click="modal = true">配置 API Key <span>↗</span></button></div><form class="composer" @submit.prevent="send()"><textarea v-model="question" aria-label="输入问题" placeholder="向 PRTS 提问，关于干员、关卡，或你想了解的泰拉……" rows="2" maxlength="2000" @keydown.enter.exact="e => { if (!e.isComposing) { e.preventDefault(); send() } }"></textarea><div class="composer-bottom"><span><Database :size="13"/> 知识库增强 <span class="enabled-dot"></span></span><div><span class="enter-tip">Enter 发送 · Shift + Enter 换行</span><button v-if="busy" type="button" class="send-button" @click="controller?.abort()" aria-label="停止生成"><Square :size="16"/></button><button v-else class="send-button" :disabled="!question.trim()" aria-label="发送问题"><ArrowUp :size="19"/></button></div></div></form><p class="footer-note">PRTS 根据本地资料生成回答，请结合引用核实。<span>BUILT FOR DOCTORS, BY DOCTORS.</span></p></div>
      </template>

      <section v-else-if="page === 'knowledge'" class="content-page"><div class="eyebrow">LOCAL KNOWLEDGE BASE</div><div class="page-heading"><div><h1>你的泰拉资料库</h1><p>把零散的资料，变成可以对话的知识。</p></div><button class="primary" :disabled="importing" @click="inputFile.click()"><Upload :size="16"/>{{ importing ? '导入中…' : '导入 Markdown' }}</button><input ref="inputFile" type="file" accept=".md" multiple hidden @change="upload"/></div><div class="stats-grid"><div><Database :size="19"/><strong>{{ knowledge.documents }}</strong><span>资料文档</span></div><div><Layers :size="19"/><strong>{{ knowledge.chunks }}</strong><span>检索片段</span></div><div><ShieldCheck :size="19"/><strong>本地</strong><span>TF-IDF 索引 · 无需额外密钥</span></div></div><div class="knowledge-guide"><FileText :size="23"/><div><h3>一份 Markdown，就是一份知识。</h3><p>使用统一的 YAML 头部记录标题、分类、来源、服务器与更新时间。导入后自动切块并更新索引；直接修改 knowledge 目录后，点击重建索引。</p><button @click="downloadTemplate">下载知识库模板 ↗</button></div></div><div class="file-toolbar"><label><Search :size="16"/><input v-model="filter" placeholder="搜索标题、文件或标签"/></label><button :disabled="indexing" @click="reindex"><RefreshCw :size="15" :class="{ spinning: indexing }"/>{{ indexing ? '重建中…' : '重建索引' }}</button></div><div v-for="f in files" :key="f.filename" class="file-row"><div class="file-icon"><FileText :size="19"/></div><div class="file-info"><strong>{{ f.title }}</strong><small>{{ f.filename }} · {{ f.server }} · 更新于 {{ f.updated }}</small></div><span class="category">{{ f.category }}</span><span class="file-size">{{ f.characters }} 字</span></div><div v-if="!files.length" class="empty-state">暂无匹配资料，请导入 Markdown 或调整搜索条件。</div><div v-for="e in knowledge.errors" :key="e.filename" class="inline-error">{{ e.filename }}：{{ e.error }}</div></section>

      <section v-else class="content-page learn-page"><div class="eyebrow">LEARN BY BUILDING</div><h1>从问题，到有据可循的回答。</h1><p class="page-description">把 learning-guide.md 中的概念，放进一个真实的 RAG 应用。</p><div class="pipeline"><span>Markdown 文档</span><b>→</b><span>切块 / TF-IDF</span><b>→</b><span>提示词 + 历史</span><b>→</b><span>DeepSeek 流式回答</span></div><div class="lesson" v-for="lesson in [{n:'01 / 02',title:'提示词与 LCEL 链',file:'backend/app/rag.py',desc:'ChatPromptTemplate 规定回答边界；prompt | model | StrOutputParser() 把消息、真实模型和正文解析串成一条链。'}, {n:'05 / 06',title:'异步流式输出与会话历史',file:'frontend/src/api.js · backend/app/rag.py',desc:'astream() 生成增量文本，经 SSE 到达浏览器。每个对话单独携带最近 12 条消息；当前检索会补充最近两条用户问题，辅助理解追问。'}, {n:'09 / 10',title:'文档切块与本地检索',file:'backend/app/knowledge.py',desc:'Document 保留来源；RecursiveCharacterTextSplitter 按 700 字切块、重叠 100 字。中文字符 n-gram TF-IDF 计算词面相似度，无需 Embedding API，但对同义改写的理解有限。'}, {n:'11 / 15',title:'RAG、引用与资料不足',file:'backend/app/rag.py',desc:'当前采用固定检索流程：每轮先检索，再生成带引用的回答。无候选时直接拒答；有候选仍要求模型判断证据是否充分。这里借鉴 15 的引用与拒答思想，未实现自主工具循环。'}]" :key="lesson.n"><span class="lesson-number">{{ lesson.n }}</span><div><h3>{{ lesson.title }}</h3><code>{{ lesson.file }}</code><p>{{ lesson.desc }}</p></div></div><div class="learning-tip"><BookOpen :size="19"/><p>动手试试：添加一份新文档，重建索引，再用不同问法提问。展开“检索参考”，观察候选是否真正支持结论。完整学习路线见项目 docs/learning-map.md。</p></div></section>
    </main>

    <div v-if="modal" class="modal-overlay" @click.self="modal = false" @keydown.esc="modal = false"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><button class="modal-close" @click="modal = false" aria-label="关闭设置"><X :size="19"/></button><div class="modal-icon"><KeyRound :size="24"/></div><div class="eyebrow">CONNECT YOUR INTELLIGENCE</div><h2 id="settings-title">连接 DeepSeek</h2><p>使用你自己的 API Key，无需注册或登录本应用。</p><label class="field">DeepSeek API Key<input v-model="key" type="password" placeholder="sk-…" autocomplete="off" spellcheck="false" @input="verified = false"/></label><div class="key-help"><span>密钥只保留在当前页面内存，刷新即清除。</span><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer">获取密钥 ↗</a></div><button class="verify-button" :disabled="!key.trim() || verifying" @click="verify"><Check v-if="verified" :size="16"/><RefreshCw v-else :size="15" :class="{ spinning: verifying }"/>{{ verifying ? '正在连接…' : verified ? '已连接 · 点击刷新模型' : '验证连接并获取模型' }}</button><label class="field">回答模型<select v-model="model"><option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }} ({{ m.id }})</option></select></label><label class="field">每次检索片段数量<select v-model="topK"><option :value="2">2 个 · 精简</option><option :value="4">4 个 · 推荐</option><option :value="6">6 个 · 更多上下文</option></select></label><p v-if="settingsError" class="inline-error">{{ settingsError }}</p><div class="privacy-note"><ShieldCheck :size="17"/><span>密钥经本地后端发送至 DeepSeek 官方接口。提问、最近对话与命中的资料会随请求发送；对话记录仅保存于此浏览器。</span></div><button class="primary full" @click="modal = false">完成配置 <span>→</span></button></section></div>
    <div v-if="toast" class="toast" role="status"><Check :size="16"/>{{ toast }}</div>
  </div>
</template>

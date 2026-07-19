<template>
  <div class="chat-app">
    <div class="chat-header">
      <h2>TalkTrace</h2>
    </div>

    <div class="chat-window" ref="chatWindow">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :ref="(el) => (messageRefs[index] = el as HTMLElement | null)"
        :class="['chat-message', isSelf(msg) ? 'self' : 'other']"
      >
        <div class="avatar-wrapper">
          <div class="avatar" :class="{ 'avatar-self': isSelf(msg) }">
            <span>{{ getEmojiForSpeaker(msg.from) }}</span>
          </div>
        </div>

        <div class="message-body">
          <div class="speaker-name" v-if="msg.from !== 'user' || !primarySpeaker">
            {{ displayName(msg.from) }}
          </div>
          <div class="bubble" v-html="renderMarkdown(msg.text)"></div>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <input v-model="input" type="text" placeholder="请输入消息" @keyup.enter="sendMessage" />
      <button @click="sendMessage" :disabled="!input.trim()">发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
//  1) 依赖 / 工具
import { ref, nextTick, watch } from 'vue'
import { useFileStore } from '@/stores/FileInfo'
import type { MessageItem } from '@/types/index'
import axios from 'axios'
import MarkdownIt from 'markdown-it'

/* Markdown 渲染：用于把消息里的 Markdown 转成 HTML */
const md = new MarkdownIt({ breaks: true })
const renderMarkdown = (text: string) => md.render(text)

//  2) Store / 响应式状态
const FileStore = useFileStore()

/* 是否处于“种子数据”状态：第一次真实输入会清空种子对话 */
const seedActive = ref(false)

/* 聊天消息 + DOM 引用（用于滚动定位） */
const messages = ref<MessageItem[]>([])
const messageRefs = ref<(HTMLElement | null)[]>([])

/* 输入输出与窗口容器 */
const input = ref<string>('')
const output = ref<string>('')
const chatWindow = ref<HTMLElement | null>(null)

/* 主讲者：用于多人会议场景中判断“谁算我” */
const primarySpeaker = ref<string | null>(null)

//  3) UI 行为：滚动/定位
const scrollToMessage = (index: number) => {
  const el = messageRefs.value[index]
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

const scrollToBottom = () => {
  const el = chatWindow.value
  if (el) el.scrollTop = el.scrollHeight
}

//  4) 昵称/头像：显示名字与 emoji 分配
const SPEAKER_EMOJIS = ['🧑', '🧑‍💼', '🧑‍🎤', '🧑‍🏫', '🧑‍💻'] as const
const speakerEmojiCache = new Map<string, string>()

function displayName(from: string): string {
  if (from === 'user') return '我'
  if (from === 'bot') return '助手'
  return from || '未知'
}

function getEmojiForSpeaker(from: string): string {
  if (from === 'user') return '👤'
  if (from === 'bot') return '🤖'

  const cached = speakerEmojiCache.get(from)
  if (cached) return cached

  const idx = speakerEmojiCache.size % SPEAKER_EMOJIS.length
  const emoji = SPEAKER_EMOJIS[idx]
  speakerEmojiCache.set(from, emoji)
  return emoji
}

/* 初始化 primarySpeaker：用于多人会议时决定“我”的身份 */
function initPrimarySpeaker(messages: MessageItem[]) {
  if (primarySpeaker.value) return

  const hasUser = messages.find((m) => m.from === 'user')
  if (hasUser) {
    primarySpeaker.value = 'user'
    return
  }

  const first = messages.find((m) => !!m.from)
  primarySpeaker.value = first?.from ?? null
}

/* 判断某条消息是不是“我说的” */
function isSelf(msg: MessageItem): boolean {
  if (msg.from === 'user') return true
  if (msg.from === 'bot') return false

  if (!primarySpeaker.value) return false
  return msg.from === primarySpeaker.value
}

//  5) 发送消息：前端 -> 后端 -> 回显 bot
let globalId = 1

// 实时抽取：发送完整历史到后端，更新可视化
const extractRealtime = async () => {
  try {
    const history = messages.value.map((m) => ({
      id: m.id,
      role: m.from === 'user' ? 'user' : 'bot',
      content: m.text,
    }))

    const resp = await fetch('http://localhost:5001/extract_realtime', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: 'default',
        history,
        reset: false,
      }),
    })

    const data = await resp.json()
    if (data.topics) {
      FileStore.setRealtimeData(data.topics, data.info_scores || [])
      console.log(`[realtime] 抽取完成: ${data.topics.length} 个 topic`)
    }
  } catch (e) {
    console.warn('[realtime] 抽取服务未启动或失败:', e)
  }
}

const sendMessage = async () => {
  const text = input.value.trim()
  if (!text) return

  /* 第一次真实输入：清掉默认消息 */
  if (seedActive.value) {
    messages.value = []
    globalId = 1
    seedActive.value = false
  }

  /* 追加用户消息 */
  const userMsg: MessageItem = { id: globalId++, text, from: 'user' }
  messages.value.push(userMsg)
  FileStore.MessageContent.push(userMsg)

  try {
    /* 请求后端返回 bot 回复 */
    const response = await axios.post('http://localhost:5000/back_message', {
      message: userMsg,
      history: FileStore.MessageContent,
    })

    output.value = response.data

    /* 追加机器人消息 */
    const botMsg: MessageItem = { id: globalId++, text: output.value, from: 'bot' }
    messages.value.push(botMsg)
    FileStore.MessageContent.push(botMsg)

    scrollToBottom()

    // 实时抽取：将完整历史发给后端做增量抽取
    await extractRealtime()
  } catch (error) {
    console.error('发送 JSON 数据失败:', error)
  } finally {
    /* 无论成功失败，都清空输入框并滚动到底 */
    input.value = ''
    nextTick(scrollToBottom)
  }
}

//  6) 数据集：加载对话文本并解析
type DatasetKey = 'meeting' | 'xinli'
type Message = ReturnType<typeof parseMeetingConversationFromText>[number]
const props = defineProps<{ datasetKey: DatasetKey }>()

const TALK_DATASETS: Record<DatasetKey, { url: string; parse: (raw: string) => Message[] }> = {
  meeting: {
    url: '/meeting_talk.txt',
    parse: parseMeetingConversationFromText,
  },
  xinli: {
    url: '/xinli_talk.md',
    parse: parseConversationFromText,
  },
}

async function loadTalk(key: DatasetKey) {
  const { url, parse } = TALK_DATASETS[key]

  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

  const rawTxt = await resp.text()
  const parsed = parse(rawTxt)

  /* 写入消息并初始化主讲者 */
  messages.value = parsed
  initPrimarySpeaker(parsed)

  /* 根据已加载数据修正 globalId，避免 id 冲突 */
  const maxId = parsed.reduce((mx, m) => Math.max(mx, m.id), 0)
  globalId = Math.max(maxId + 1, 1)

  /* 标记为种子数据（下一次真实输入会清空） */
  seedActive.value = true
  await nextTick()
  scrollToBottom()
}

//  7) 解析函数：不同数据集不同解析方式
/* 解析 xinli_talk.md：按 Prompt/Response 块切分 */
function parseConversationFromText(raw: string): MessageItem[] {
  const result: MessageItem[] = []
  let idCounter = 1
  let role: 'user' | 'bot' | null = null
  let content = ''

  const lines = raw.split(/\r?\n/)

  for (const line of lines) {
    const trimmed = line.trim()

    if (trimmed.startsWith('## Prompt:') || trimmed.startsWith('## Prompt：')) {
      if (content && role) {
        result.push({ id: idCounter, from: role, text: content.trim() })
        idCounter += 1
        content = ''
      }
      role = 'user'
      continue
    }

    if (trimmed.startsWith('## Response:') || trimmed.startsWith('## Response：')) {
      if (content && role) {
        result.push({ id: idCounter, from: role, text: content.trim() })
        idCounter += 1
        content = ''
      }
      role = 'bot'
      continue
    }

    if (role) content += line + '\n'
  }

  if (content && role) {
    result.push({ id: idCounter, from: role, text: content.trim() })
  }

  return result
}

/* 解析 meeting_talk.txt：按 “纯数字 id 行 + [speaker] 内容” 的格式解析 */
function parseMeetingConversationFromText(raw: string): MessageItem[] {
  const result: MessageItem[] = []

  let currentId: number | null = null
  let currentSpeaker: string | null = null
  let contentLines: string[] = []

  const lines = raw.split(/\r?\n/)

  const flushCurrent = () => {
    if (currentId != null && currentSpeaker && contentLines.length > 0) {
      result.push({
        id: currentId,
        from: currentSpeaker,
        text: contentLines.join('\n').trim(),
      })
    }
    contentLines = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    if (/^\d+$/.test(trimmed)) {
      flushCurrent()
      currentId = parseInt(trimmed, 10)
      currentSpeaker = null
      continue
    }

    const match = trimmed.match(/^\[(.+?)\](.*)$/)
    if (match) {
      flushCurrent()

      if (currentId == null) {
        currentId = result.length + 1
      }

      currentSpeaker = match[1].trim() || 'Unknown'
      const firstText = match[2].trim()
      if (firstText) contentLines.push(firstText)
      continue
    }

    if (currentId != null) contentLines.push(trimmed)
  }

  flushCurrent()
  return result
}

//  8) Watch：与可视化联动 / 切换数据集
/* 点击 slot 后：聊天窗口滚动到对应 id 的消息 */
watch(
  () => FileStore.selectedSlotId,
  (slotId) => {
    if (!slotId) return
    const index = messages.value.findIndex((msg) => msg.id === slotId)
    if (index !== -1) scrollToMessage(index)
  },
)

/* 触发 refreshKey：清空聊天窗口（用于“新开分支”等操作） */
watch(
  () => FileStore.refreshKey,
  (newVal, oldVal) => {
    if (newVal !== oldVal) {
      messages.value = []
      input.value = ''
      output.value = ''
      globalId = 1
      nextTick(scrollToBottom)
      console.log('对话窗口已清空')
    }
  },
)

/* 切换数据集：加载对应文本并解析 */
watch(
  () => props.datasetKey,
  (key) => {
    messages.value = []
    seedActive.value = false
    loadTalk(key).catch((e) => console.error('加载对话失败：', e))
  },
  { immediate: true },
)
</script>

<style scoped>
.chat-app {
  display: flex;
  flex-direction: column;
  height: 98vh;

  /* 更接近 IM 的柔和底色 */
  background: linear-gradient(180deg, #f6f7fb 0%, #f2f4f8 100%);
  font-family:
    ui-sans-serif,
    system-ui,
    -apple-system,
    'Segoe UI',
    'PingFang SC',
    'Hiragino Sans GB',
    'Microsoft YaHei',
    Arial;
  color: #1f2937;

  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

/* 顶部栏：更像 app header */
.chat-header {
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(10px);

  padding: 12px 14px 10px;
  text-align: center;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.chat-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.2px;
}

/* 消息窗口 */
.chat-window {
  flex: 1;
  padding: 14px 12px 18px;
  overflow-y: auto;

  /* 保持你隐藏滚动条的逻辑 */
  scrollbar-width: none;
  -ms-overflow-style: none;

  /* 更像聊天背景的“纸感” */
  background-image: radial-gradient(rgba(15, 23, 42, 0.04) 1px, transparent 1px);
  background-size: 18px 18px;
  background-position: 0 0;
}

.chat-window::-webkit-scrollbar {
  display: none;
}

/* 一条消息 */
.chat-message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}

/* 自己：右侧 */
.chat-message.self {
  flex-direction: row-reverse;
}

/* 头像区 */
.avatar-wrapper {
  width: 40px;
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;

  background: #e5e7eb;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.1);
  border: 1px solid rgba(15, 23, 42, 0.06);
  user-select: none;
}

.avatar span {
  font-size: 18px;
  line-height: 1;
}

.avatar-self {
  background: linear-gradient(180deg, #34d399 0%, #22c55e 100%);
  color: #fff;
  border: 1px solid rgba(34, 197, 94, 0.35);
}

/* 消息主体 */
.message-body {
  max-width: min(78%, 720px);
  display: flex;
  flex-direction: column;
}

/* 昵称 */
.speaker-name {
  font-size: 12px;
  color: rgba(31, 41, 55, 0.55);
  margin: 0 8px 6px;
}

/* 气泡 */
.bubble {
  position: relative;
  max-width: 100%;
  padding: 10px 12px;
  border-radius: 14px;

  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);

  word-break: break-word;
  line-height: 1.55;
  font-size: 14px;
}

/* 让 Markdown 内容更好看 */
.bubble :deep(p) {
  margin: 0.25em 0;
}
.bubble :deep(ul),
.bubble :deep(ol) {
  margin: 0.35em 0 0.35em 1.2em;
  padding: 0;
}
.bubble :deep(li) {
  margin: 0.2em 0;
}
.bubble :deep(a) {
  color: #2563eb;
  text-decoration: none;
}
.bubble :deep(a:hover) {
  text-decoration: underline;
}
.bubble :deep(code) {
  font-family:
    ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
    monospace;
  font-size: 12.5px;
  padding: 0.15em 0.35em;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.06);
  border: 1px solid rgba(15, 23, 42, 0.08);
}
.bubble :deep(pre) {
  margin: 0.6em 0 0.2em;
  padding: 10px 12px;
  border-radius: 12px;
  background: #0b1220;
  color: rgba(255, 255, 255, 0.92);
  overflow: auto;
}
.bubble :deep(pre code) {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
}

/* 自己的气泡：绿色渐变 */
.chat-message.self .bubble {
  background: linear-gradient(180deg, #34d399 0%, #22c55e 100%);
  color: #fff;
  border: 1px solid rgba(34, 197, 94, 0.45);
  box-shadow: 0 12px 30px rgba(34, 197, 94, 0.18);
}

/* 自己气泡里链接/代码的适配 */
.chat-message.self .bubble :deep(a) {
  color: rgba(255, 255, 255, 0.95);
  text-decoration: underline;
}
.chat-message.self .bubble :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: rgba(255, 255, 255, 0.95);
}
.chat-message.self .bubble :deep(pre) {
  background: rgba(0, 0, 0, 0.28);
}

.chat-input {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;

  background: rgba(255, 255, 255, 0.92);
  border-top: 1px solid rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(10px);
}

.chat-input input {
  flex: 1;
  height: 42px;
  padding: 0 14px;

  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.96);

  color: #111827;
  outline: none;

  transition:
    box-shadow 0.15s ease,
    border-color 0.15s ease;
}

.chat-input input::placeholder {
  color: rgba(31, 41, 55, 0.45);
}

.chat-input input:focus {
  border-color: rgba(34, 197, 94, 0.55);
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.18);
}

.chat-input button {
  height: 42px;
  padding: 0 18px;
  border-radius: 999px;

  border: 1px solid rgba(34, 197, 94, 0.25);
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;

  font-weight: 700;
  cursor: pointer;

  transition:
    transform 0.08s ease,
    filter 0.15s ease,
    background 0.15s ease;
}

.chat-input button:hover {
  background: rgba(34, 197, 94, 0.18);
  filter: brightness(1.02);
}

.chat-input button:active {
  transform: translateY(1px);
}

.chat-input button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>

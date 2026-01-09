<template>
  <div class="chat-app">
    <!-- 顶部标题 -->
    <div class="chat-header">
      <h2>ChatApp</h2>
      <p class="sub-title">自然语言模型人工智能对话</p>
    </div>

    <!-- 聊天窗口 -->
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

    <!-- 输入区域 -->
    <div class="chat-input">
      <input v-model="input" type="text" placeholder="请输入消息" @keyup.enter="sendMessage" />
      <button @click="sendMessage" :disabled="!input.trim()">发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { useFileStore } from '@/stores/FileInfo'
import type { MessageItem } from '@/types/index'
import axios from 'axios'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  breaks: true, // 单行换行变 <br>
})
const renderMarkdown = (text: string) => {
  return md.render(text)
}

const FileStore = useFileStore()
const seedActive = ref(false)

const messages = ref<MessageItem[]>([])
const messageRefs = ref<(HTMLElement | null)[]>([])

const input = ref<string>('')
const output = ref<string>('')
const chatWindow = ref<HTMLElement | null>(null)

// 滚动到指定消息
const scrollToMessage = (index: number) => {
  const el = messageRefs.value[index]
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

const SPEAKER_EMOJIS = ['🧑', '🧑‍💼', '🧑‍🎤', '🧑‍🏫', '🧑‍💻'] as const

const speakerEmojiCache = new Map<string, string>()

function displayName(from: string): string {
  if (from === 'user') return '我'
  if (from === 'bot') return '助手'
  return from || '未知'
}

function getEmojiForSpeaker(from: string): string {
  // 先处理 user / bot
  if (from === 'user') return '👤'
  if (from === 'bot') return '🤖'

  // 多人会议：如果之前给他分配过 emoji，直接复用
  const cached = speakerEmojiCache.get(from)
  if (cached) return cached

  // 没分配过，就按当前 cache 的大小轮流分配一个
  const idx = speakerEmojiCache.size % SPEAKER_EMOJIS.length
  const emoji = SPEAKER_EMOJIS[idx]
  speakerEmojiCache.set(from, emoji)
  return emoji
}

const primarySpeaker = ref<string | null>(null)

function initPrimarySpeaker(messages: MessageItem[]) {
  if (primarySpeaker.value) return
  // 优先兼容旧格式：如果有 user，就直接用 user
  const hasUser = messages.find((m) => m.from === 'user')
  if (hasUser) {
    primarySpeaker.value = 'user'
    return
  }
  // 否则就是多人会议：取第一条有 from 的作为“我”
  const first = messages.find((m) => !!m.from)
  primarySpeaker.value = first?.from ?? null
}

// 判断某条消息是不是“我说的”
function isSelf(msg: MessageItem): boolean {
  // 旧的 LLM 对话：user 在右，bot 在左
  if (msg.from === 'user') return true
  if (msg.from === 'bot') return false

  // 多人会议：from 等于 primarySpeaker 就算“我”
  if (!primarySpeaker.value) return false
  return msg.from === primarySpeaker.value
}

let globalId = 1 // 全局自增
// let reset_flag = false
// let allMessages: { id: number; role: string; content: string }[] = []
const sendMessage = async () => {
  const text = input.value.trim()
  if (!text) return

  // ⛳ 第一次真实输入：清掉默认消息，不影响 Pinia
  if (seedActive.value) {
    messages.value = []
    // allMessages = []
    globalId = 1
    // reset_flag = true // 首条作为新会话
    seedActive.value = false
  }

  // 添加用户消息
  const userMsg: MessageItem = { id: globalId++, text, from: 'user' }
  messages.value.push(userMsg)
  FileStore.MessageContent.push(userMsg)

  try {
    // 发送消息给机器人
    const response = await axios.post('http://localhost:5000/back_message', {
      message: userMsg,
      history: FileStore.MessageContent,
    })
    console.log('机器人回复:', response.data)
    output.value = response.data

    // 模拟机器人回复
    const botMsg: MessageItem = { id: globalId++, text: output.value, from: 'bot' }
    messages.value.push(botMsg)
    FileStore.MessageContent.push(botMsg)
    scrollToBottom()
    // 构建用户 + bot 消息数组，传给 /extract
    // allMessages = FileStore.MessageContent.map((msg) => ({
    //   id: msg.id,
    //   role: msg.from,
    //   content: msg.text,
    // }))

    // // 把用户和模型的消息抽传给后端
    // console.log('发送到 /extract 的内容:', allMessages)

    // const extractResponse = await axios.post('http://localhost:5000/extract', {
    //   content: allMessages,
    //   reset: reset_flag,
    //   history: FileStore.MessageContent,
    // })
    // FileStore.GPTContent = extractResponse.data
    // reset_flag = false // ✅ 立刻复位！否则每次都会清空后端聚合
  } catch (error) {
    console.error('发送 JSON 数据失败:', error)
  } finally {
    // 无论成功失败，都清空输入框
    input.value = ''
    nextTick(scrollToBottom)
  }
}

const scrollToBottom = () => {
  const el = chatWindow.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

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
    parse: parseConversationFromText, // ⭐ 你原来注释的那个
  },
}
async function loadTalk(key: DatasetKey) {
  const { url, parse } = TALK_DATASETS[key]

  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

  const rawTxt = await resp.text()
  const parsed = parse(rawTxt)

  messages.value = parsed
  initPrimarySpeaker(parsed)

  const maxId = parsed.reduce((mx, m) => Math.max(mx, m.id), 0)
  globalId = Math.max(maxId + 1, 1)

  seedActive.value = true
  await nextTick()
  scrollToBottom()
}

function parseConversationFromText(raw: string): MessageItem[] {
  const result: MessageItem[] = []
  let idCounter = 1
  let role: 'user' | 'bot' | null = null
  let content = ''

  const lines = raw.split(/\r?\n/)

  for (const line of lines) {
    const trimmed = line.trim()

    if (trimmed.startsWith('## Prompt:') || trimmed.startsWith('## Prompt：')) {
      // flush 上一段
      if (content && role) {
        result.push({
          id: idCounter,
          from: role,
          text: content.trim(),
        })
        idCounter += 1
        content = ''
      }
      role = 'user'
      continue
    }

    if (trimmed.startsWith('## Response:') || trimmed.startsWith('## Response：')) {
      if (content && role) {
        result.push({
          id: idCounter,
          from: role,
          text: content.trim(),
        })
        idCounter += 1
        content = ''
      }
      role = 'bot'
      continue
    }

    if (role) {
      content += line + '\n'
    }
  }

  // 收尾
  if (content && role) {
    result.push({
      id: idCounter,
      from: role,
      text: content.trim(),
    })
  }

  return result
}

function parseMeetingConversationFromText(raw: string): MessageItem[] {
  const result: MessageItem[] = []

  let currentId: number | null = null
  let currentSpeaker: string | null = null
  let contentLines: string[] = []

  const lines = raw.split(/\r?\n/)

  // 小工具：把当前缓存的这条消息 push 进去
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
    if (!trimmed) {
      // 空行直接跳过，不当成内容
      continue
    }

    // 1) 纯数字行：表示一个新的发言 id
    if (/^\d+$/.test(trimmed)) {
      // 先把上一条完整消息收尾
      flushCurrent()

      currentId = parseInt(trimmed, 10)
      currentSpeaker = null
      continue
    }

    // 2) [说话人]内容
    const match = trimmed.match(/^\[(.+?)\](.*)$/)
    if (match) {
      // 理论上每个 id 对应一次 speaker 行，这里也先 flush 一下以防同 id 多 speaker 的奇怪情况
      flushCurrent()

      if (currentId == null) {
        // 如果文本坏掉了，没有 id 就出现了说话人，就临时给个 id
        currentId = result.length + 1
      }

      currentSpeaker = match[1].trim() || 'Unknown'
      const firstText = match[2].trim()
      if (firstText) {
        contentLines.push(firstText)
      }
      continue
    }

    // 3) 其他普通文本行：视为当前发言的后续内容
    if (currentId != null) {
      contentLines.push(trimmed)
    }
    // 如果连 currentId 都没有，就忽略这行
  }

  // 文件结束，处理最后一条
  flushCurrent()

  return result
}

watch(
  () => FileStore.selectedSlotId,
  (slotId) => {
    if (!slotId) return
    const index = messages.value.findIndex((msg) => msg.id === slotId)
    if (index !== -1) {
      scrollToMessage(index)
    }
  },
)
watch(
  () => FileStore.refreshKey,
  (newVal, oldVal) => {
    if (newVal !== oldVal) {
      // ✅ 清空当前对话消息
      messages.value = []
      // allMessages = []

      // ✅ 可选：重置输入框等状态
      input.value = ''
      output.value = ''

      globalId = 1
      // reset_flag = true

      // ✅ 清空界面滚动
      nextTick(scrollToBottom)
      console.log('对话窗口已清空')
    }
  },
)
watch(
  () => props.datasetKey,
  (key) => {
    // 切换时建议清一下旧状态（可选但稳）
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
  height: 95vh;
  background: #f5f5f5;
  font-family: Arial, sans-serif;
}

.chat-header {
  background: #eee;
  padding: 15px;
  text-align: center;
  border-bottom: 1px solid #ccc;
}

.chat-header h2 {
  margin: 0;
}

.sub-title {
  font-size: 12px;
  color: #888;
}

.chat-window {
  flex: 1;
  padding: 15px;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.chat-window::-webkit-scrollbar {
  display: none;
}

.chat-message {
  display: flex;
  align-items: flex-start;
  margin-bottom: 16px;
}

/* 自己在右边：整行反转 */
.chat-message.self {
  flex-direction: row-reverse;
}

/* 头像外层：固定宽度，保证气泡起点对齐 */
.avatar-wrapper {
  width: 40px;
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}

.avatar {
  width: 32px;
  height: 32px;
  background: #ccc;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-self {
  background: #36ae44;
  color: #fff;
  font-weight: 600;
}

/* 名字 + 气泡的容器 */
.message-body {
  max-width: 80%;
  display: flex;
  flex-direction: column;
}

/* 名字在气泡上方，宽度随气泡，但不影响头像 */
.speaker-name {
  font-size: 12px;
  color: #666;
  margin: 0 4px 4px 4px;
}

/* 气泡 */
.bubble {
  align-self: flex-start;
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 6px;
  background: #ddd;
  word-break: break-word;
}

/* 自己说的话的气泡颜色 + 右对齐 */
.chat-message.self .bubble {
  background: #36ae44;
  color: #fff;
  align-self: flex-end; /* 让气泡贴近右边 */
}

.chat-input {
  display: flex;
  padding: 10px;
  background: #fff;
  border-top: 1px solid #ccc;
}

.chat-input input {
  flex: 1;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 5px;
  margin-right: 5px;
}

.chat-input button {
  padding: 8px 12px;
  border: none;
  background: #36ae44;
  color: #fff;
  border-radius: 5px;
  cursor: pointer;
}

.chat-input button:disabled {
  background: #aaa;
  cursor: not-allowed;
}
</style>

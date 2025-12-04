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
        :class="['chat-message', msg.from]"
      >
        <div class="avatar">
          <span>{{ msg.from === 'user' ? '👤' : '🤖' }}</span>
        </div>
        <div class="bubble" v-html="renderMarkdown(msg.text)"></div>
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
import { ref, nextTick, watch, onMounted } from 'vue'
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
const seedActive = ref(false) // 正在展示默认初始对话吗？

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
let globalId = 1 // 全局自增
let reset_flag = false
let allMessages: { id: number; role: 'user' | 'bot'; content: string }[] = []
const sendMessage = async () => {
  const text = input.value.trim()
  if (!text) return

  // ⛳ 第一次真实输入：清掉默认消息，不影响 Pinia
  if (seedActive.value) {
    messages.value = []
    allMessages = []
    globalId = 1
    reset_flag = true // 首条作为新会话
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
    allMessages = FileStore.MessageContent.map((msg) => ({
      id: msg.id,
      role: msg.from,
      content: msg.text,
    }))

    // 把用户和模型的消息抽传给后端
    console.log('发送到 /extract 的内容:', allMessages)

    const extractResponse = await axios.post('http://localhost:5000/extract', {
      content: allMessages,
      reset: reset_flag,
      history: FileStore.MessageContent,
    })
    FileStore.GPTContent = extractResponse.data
    reset_flag = false // ✅ 立刻复位！否则每次都会清空后端聚合
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
      allMessages = []

      // ✅ 可选：重置输入框等状态
      input.value = ''
      output.value = ''

      globalId = 1
      reset_flag = true

      // ✅ 清空界面滚动
      nextTick(scrollToBottom)
      console.log('对话窗口已清空')
    }
  },
)
onMounted(async () => {
  if (messages.value.length > 0) return
  try {
    const resp = await fetch('/ChatGPT-xinli.md')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

    const rawTxt = await resp.text()
    const parsed = parseConversationFromText(rawTxt)

    messages.value = parsed

    // 计算全局 id 起点，避免后续新增消息冲突
    const maxId = parsed.reduce((mx, m) => Math.max(mx, m.id), 0)
    globalId = Math.max(maxId + 1, 1)

    seedActive.value = true
    await nextTick()
    scrollToBottom()
  } catch (e) {
    console.error('加载默认对话失败：', e)
  }
})
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
  scrollbar-width: none; /* Firefox 隐藏滚动条 */
  -ms-overflow-style: none; /* IE 和 Edge 隐藏滚动条 */
}

.chat-window::-webkit-scrollbar {
  display: none;
}

.chat-message {
  display: flex;
  align-items: flex-start;
  margin-bottom: 10px;
}

.chat-message.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 32px;
  height: 32px;
  background: #ccc;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
}

.bubble {
  max-width: 60%;
  padding: 10px;
  border-radius: 10px;
  background: #ddd;
  word-break: break-word;
}

.chat-message.user .bubble {
  background: #36ae44;
  color: #fff;
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

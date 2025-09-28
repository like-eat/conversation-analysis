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
        <div class="bubble">
          {{ msg.text }}
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

const FileStore = useFileStore()

const messages = ref<MessageItem[]>([{ text: '你好，我是对话助手！', from: 'bot' }])
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

const sendMessage = async () => {
  const text = input.value.trim()
  if (!text) return

  // 添加用户消息
  messages.value.push({ text, from: 'user' })
  FileStore.MessageContent.push({ text, from: 'user' })

  try {
    // 发送消息给机器人
    const response = await axios.post('http://localhost:5000/back_message', { text })
    console.log('机器人回复:', response.data)
    output.value = response.data

    // 模拟机器人回复
    messages.value.push({ text: output.value, from: 'bot' })
    FileStore.MessageContent.push({ text: output.value, from: 'bot' })
    scrollToBottom()
    // 过滤用户消息
    const userMessages = FileStore.MessageContent.filter((msg) => msg.from === 'user').map(
      (msg) => msg.text,
    )
    // 接着提取问题
    console.log('发送到 /extract 的内容:', userMessages)
    const extractResponse = await axios.post('http://localhost:5000/extract', {
      content: userMessages,
    })
    FileStore.GPTContent = extractResponse.data
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

watch(
  () => FileStore.selectedMessage,
  (sentence) => {
    if (!sentence) return
    const index = messages.value.findIndex((msg) => msg.text === sentence)
    if (index !== -1) {
      scrollToMessage(index)
    }
  },
)
</script>
<style scoped>
.chat-app {
  display: flex;
  flex-direction: column;
  height: 85vh;
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
  background: #49f55d;
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
  background: #49f55d;
  color: #fff;
  border-radius: 5px;
  cursor: pointer;
}

.chat-input button:disabled {
  background: #aaa;
  cursor: not-allowed;
}
</style>

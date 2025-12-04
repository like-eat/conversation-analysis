import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { MessageItem, Conversation } from '@/types/index'

export const useCounterStore = defineStore('counter', () => {
  const count = ref(0)
  const doubleCount = computed(() => count.value * 2)
  function increment() {
    count.value++
  }

  return { count, doubleCount, increment }
})

export const useFileStore = defineStore('refileInfo', {
  state() {
    return {
      // 历史对话内容
      MessageContent: [] as MessageItem[],
      // GPT生成的对话内容
      GPTContent: [] as Conversation[],
      // 选中的slot id来定位对话
      selectedSlotId: null as number | null,
      // 控制左侧是否刷新
      refreshKey: 0,
    }
  },
  actions: {
    setMessageContent(content: MessageItem[]) {
      this.MessageContent = content
    },
    clearMessageContent() {
      this.MessageContent = []
    },
    clearGPTContent() {
      this.GPTContent = []
    },
    triggerRefresh() {
      this.refreshKey++ // ✅ 每次新建分支时+1
    },
  },
})

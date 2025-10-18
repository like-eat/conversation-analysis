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
      MessageContent: [] as MessageItem[],
      GPTContent: [] as Conversation[],
      FileContent: '',
      selectedSlotId: null as number | null,
      refreshKey: 0, // 控制左侧对话更新
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

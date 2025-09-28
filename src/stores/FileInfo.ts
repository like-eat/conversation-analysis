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
      selectedMessage: null as string | null,
      FileContent: '',
    }
  },
  actions: {
    clearMessageContent() {
      this.MessageContent = []
    },
    clearGPTContent() {
      this.GPTContent = []
    },
  },
})

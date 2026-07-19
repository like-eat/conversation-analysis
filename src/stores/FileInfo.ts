import { defineStore } from 'pinia'
import type { MessageItem, Conversation } from '@/types/index'

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
      // 实时抽取：topic 数据
      realtimeTopics: [] as Conversation[],
      // 实时抽取：信息量评分
      realtimeScores: [] as { id: number; info_score: number }[],
    }
  },
  actions: {
    setMessageContent(content: MessageItem[]) {
      this.MessageContent = content
    },
    triggerRefresh() {
      this.refreshKey++
    },
    setRealtimeData(topics: Conversation[], scores: { id: number; info_score: number }[]) {
      this.realtimeTopics = topics
      this.realtimeScores = scores
    },
    clearRealtimeData() {
      this.realtimeTopics = []
      this.realtimeScores = []
    },
  },
})

export interface Slot {
  id: number
  sentence: string
  slot: string
  color: string
  source: 'user' | 'bot'
  x?: number // 新增
  y?: number // 新增
}
export interface Conversation {
  id: number
  domain: string
  slots: Slot[]
  color: string
  x?: number // 新增
  y?: number // 新增
}

export interface MessageItem {
  id: number
  text: string
  from: 'user' | 'bot'
}

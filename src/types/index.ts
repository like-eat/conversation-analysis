export interface Slot {
  id: number
  sentence: string
  slot: string
  color: string
  source: 'user' | 'bot'
  x?: number // 新增
  y?: number // 新增
  rw?: number // 新增
  rh?: number // 新增
}
export interface Conversation {
  id: number
  topic: string
  slots: Slot[]
  color: string
  w?: number
  h?: number
  cx?: number
  cy?: number
}

export interface MessageItem {
  id: number
  text: string
  from: 'user' | 'bot'
}

export interface Point {
  topic: string
  slot: string
  id: number
  topicColor: string
  source: 'user' | 'bot'
}

export interface Segment {
  id: number
  left: number
  right: number
}

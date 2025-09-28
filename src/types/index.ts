export interface Node {
  id: string
  group: number
  timeOrder: number
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
  vx?: number
  vy?: number
  index?: number
}

export interface Link {
  source: string | Node
  target: string | Node
  value: number
  group: number
  index?: number
}

export interface GraphData {
  nodes: Node[]
  links: Link[]
}

export interface MessageItem {
  text: string
  from: 'user' | 'bot'
}

export interface Slot {
  sentence: string
  slot: string
  color: string
}
export interface Conversation {
  domain: string
  slots: Slot[]
  color: string
}

export interface MessageItem {
  text: string
  from: 'user' | 'bot'
}

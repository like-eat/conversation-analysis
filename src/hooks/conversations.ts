// src/utils/conversations.ts
import type { Conversation, Slot, MessageItem } from '@/types/index'

/** Conversation[] -> MessageItem[]（按 domain 出现顺序 + slot.id 排序） */
export function conversationsToMessages(convs: Conversation[]): MessageItem[] {
  const withOrder = convs.map((c, i) => ({ ...c, _order: i }))
  const slots: (Slot & { _order: number })[] = withOrder.flatMap((c) =>
    (c.slots ?? []).map((s) => ({ ...s, _order: c._order })),
  )
  slots.sort((a, b) => a._order - b._order || (a.id ?? 0) - (b.id ?? 0))

  let autoinc = 1
  return slots.map((s) => ({
    id: typeof s.id === 'number' ? s.id : autoinc++,
    from: s.source === 'user' ? 'user' : 'bot',
    text: s.sentence ?? s.slot ?? '',
  }))
}

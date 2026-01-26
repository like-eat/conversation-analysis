import * as d3 from 'd3'

import type { Point, Segment } from '@/types/index'
// ⚠️ 你 Methods.ts 里应该已有 layoutMinMove；这里直接用它
// import { layoutMinMove } from './Methods' // 不要这样自引；在同文件里就直接调用即可

export type WiggleEvt = { rowId: number; topic: string; dir: 'L' | 'R'; weight: number }
export type WiggleInterval = { s: number; e: number; rows: number[] }

export type WiggleSecondPassParams = {
  ENABLE_WIGGLE_SECOND_PASS: boolean
  allPoints: Point[]
  xs: number[]
  topics: string[]
  rowProfile: Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>
  widthByTopicById: Map<string, Map<number, number>>
  topicBands: Map<string, Segment[]>
  topicBandById: Map<string, Map<number, Segment>>
  fixedXInTopicRow: (topic: string, p: Point) => number
  MIN_WIDTH: number

  // 可选调参
  WIGGLE_JUMP_TH?: number
  WIGGLE_GAP?: number
  MAX_MOVE_TOPICS?: number
  MAX_SWAPS_PER_TOPIC?: number
  MIN_ROW_TOPICS_TO_EDIT?: number

  DEBUG_WIGGLE?: boolean
}

export type WiggleSecondPassResult = {
  topicBands: Map<string, Segment[]>
  topicBandById: Map<string, Map<number, Segment>>
  // debug 可选输出（方便你在主组件 console）
  debug?: {
    wiggleRowsUniq: number[]
    intervals: Array<{ s: number; e: number; len: number }>
    changedRows: number[]
  }
}

// ---------- 小工具 ----------
function clamp01(x: number) {
  return Math.max(0, Math.min(1, x))
}

function buildTopicBandById(topicBands: Map<string, Segment[]>): Map<string, Map<number, Segment>> {
  const topicBandById = new Map<string, Map<number, Segment>>()
  topicBands.forEach((segs, topic) => {
    const m = new Map<number, Segment>()
    segs.forEach((s) => m.set(s.id, s))
    topicBandById.set(topic, m)
  })
  return topicBandById
}

function buildPresentTopicsByRow(
  xs: number[],
  topics: string[],
  widthByTopicById: Map<string, Map<number, number>>,
  MIN_WIDTH: number,
): Map<number, Set<string>> {
  const m = new Map<number, Set<string>>()
  xs.forEach((id) => {
    const set = new Set<string>()
    for (const t of topics) {
      const w = widthByTopicById.get(t)!.get(id) ?? 0
      if (w > MIN_WIDTH) set.add(t)
    }
    m.set(id, set)
  })
  return m
}

function pointU(params: {
  p: Point
  rowProfile: Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>
  fixedXInTopicRow: (topic: string, p: Point) => number
}): number | null {
  const { p, rowProfile, fixedXInTopicRow } = params
  const rp = rowProfile.get(p.id)
  if (!rp) return null
  const x = fixedXInTopicRow(p.topic, p)
  const denom = rp.stripRight - rp.stripLeft
  if (denom <= 1e-6) return null
  return clamp01((x - rp.stripLeft) / denom)
}

function detectWiggles(params: {
  allPoints: Point[]
  WIGGLE_JUMP_TH: number
  rowProfile: Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>
  fixedXInTopicRow: (topic: string, p: Point) => number
}): { wiggleRows: number[]; rowEvents: Map<number, WiggleEvt[]> } {
  const { allPoints, WIGGLE_JUMP_TH, rowProfile, fixedXInTopicRow } = params
  const rowEvents = new Map<number, WiggleEvt[]>()
  const wiggleRows: number[] = []

  const bySpeaker = d3.group(allPoints, (d) => (d.source || '').trim())
  bySpeaker.forEach((pts, sp) => {
    if (!sp) return
    const sorted = pts.slice().sort((a, b) => a.id - b.id)
    for (let i = 1; i < sorted.length; i++) {
      const p0 = sorted[i - 1]
      const p1 = sorted[i]

      const u0 = pointU({ p: p0, rowProfile, fixedXInTopicRow })
      const u1 = pointU({ p: p1, rowProfile, fixedXInTopicRow })
      if (u0 == null || u1 == null) continue

      const flip = (u0 - 0.5) * (u1 - 0.5) < 0
      const jump = Math.abs(u1 - u0) > WIGGLE_JUMP_TH
      if (!flip || !jump) continue

      const rowId = p1.id
      wiggleRows.push(rowId)

      // u1<u0：往左跳，期望把它“推回右边”(R)；反之推左(L)
      const dir: 'L' | 'R' = u1 < u0 ? 'R' : 'L'
      const weight = Math.abs(u1 - u0)

      const arr = rowEvents.get(rowId) ?? []
      arr.push({ rowId, topic: p1.topic, dir, weight })
      rowEvents.set(rowId, arr)
    }
  })

  return { wiggleRows, rowEvents }
}

function groupToIntervals(rows: number[], gap = 1): WiggleInterval[] {
  const uniq = Array.from(new Set(rows)).sort((a, b) => a - b)
  if (!uniq.length) return []
  const res: WiggleInterval[] = []

  let s = uniq[0]
  let prev = uniq[0]
  let cur = [uniq[0]]

  for (let i = 1; i < uniq.length; i++) {
    const x = uniq[i]
    if (x - prev <= gap) cur.push(x)
    else {
      res.push({ s, e: prev, rows: cur })
      s = x
      cur = [x]
    }
    prev = x
  }
  res.push({ s, e: prev, rows: cur })
  return res
}

function deriveIntervalPlan(params: {
  baseOrder: string[]
  intervalRows: number[]
  rowEvents: Map<number, WiggleEvt[]>
  presentTopicsByRow: Map<number, Set<string>>
  MAX_MOVE_TOPICS: number
  MAX_SWAPS_PER_TOPIC: number
  MIN_ROW_TOPICS_TO_EDIT: number
}): { order: string[]; moveTopics: Set<string> } {
  const {
    baseOrder,
    intervalRows,
    rowEvents,
    presentTopicsByRow,
    MAX_MOVE_TOPICS,
    MAX_SWAPS_PER_TOPIC,
    MIN_ROW_TOPICS_TO_EDIT,
  } = params

  const net = new Map<string, number>()

  for (const rowId of intervalRows) {
    const pres = presentTopicsByRow.get(rowId)
    if (!pres || pres.size < MIN_ROW_TOPICS_TO_EDIT) continue
    const evs = rowEvents.get(rowId) ?? []
    for (const e of evs) {
      if (!pres.has(e.topic)) continue
      const v = (net.get(e.topic) ?? 0) + (e.dir === 'R' ? e.weight : -e.weight)
      net.set(e.topic, v)
    }
  }

  const candidates = Array.from(net.entries())
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, MAX_MOVE_TOPICS)

  const moveTopics = new Set<string>(candidates.map((d) => d[0]))
  const order = baseOrder.slice()

  function swapUseful(a: string, b: string): boolean {
    let cnt = 0
    for (const rowId of intervalRows) {
      const pres = presentTopicsByRow.get(rowId)
      if (pres && pres.has(a) && pres.has(b)) cnt++
    }
    // ✅ 这里我用一个“更不苛刻”的阈值，避免经常完全不交换
    return cnt >= Math.max(1, Math.floor(intervalRows.length * 0.25))
  }

  for (const [t, score] of candidates) {
    const dir = score > 0 ? 'R' : 'L'
    for (let step = 0; step < MAX_SWAPS_PER_TOPIC; step++) {
      const i = order.indexOf(t)
      if (i < 0) break

      if (dir === 'R' && i < order.length - 1) {
        const nb = order[i + 1]
        if (!swapUseful(t, nb)) break
        ;[order[i], order[i + 1]] = [order[i + 1], order[i]]
      } else if (dir === 'L' && i > 0) {
        const nb = order[i - 1]
        if (!swapUseful(nb, t)) break
        ;[order[i - 1], order[i]] = [order[i], order[i - 1]]
      }
    }
  }

  return { order, moveTopics }
}

function expandIntervalByCoPresence(params: {
  itv: WiggleInterval
  moveTopics: Set<string>
  presentTopicsByRow: Map<number, Set<string>>
  xs: number[]
}): WiggleInterval {
  const { itv, moveTopics, presentTopicsByRow, xs } = params

  if (moveTopics.size < 2) return itv

  const seed = itv.rows[Math.floor(itv.rows.length / 2)]
  const idx0 = xs.indexOf(seed)
  if (idx0 < 0) return itv

  const ok = (rowId: number) => {
    const pres = presentTopicsByRow.get(rowId)
    if (!pres) return false
    for (const t of moveTopics) if (!pres.has(t)) return false
    return true
  }

  if (!ok(seed)) return itv

  let i = idx0
  while (i - 1 >= 0 && ok(xs[i - 1])) i--
  const s2 = xs[i]

  let j = idx0
  while (j + 1 < xs.length && ok(xs[j + 1])) j++
  const e2 = xs[j]

  const rows2: number[] = []
  for (const id of xs) {
    if (id < s2 || id > e2) continue
    if (ok(id)) rows2.push(id)
  }

  return { s: s2, e: e2, rows: rows2.length ? rows2 : itv.rows }
}

function buildRowOrderMap(params: {
  baseOrder: string[]
  intervals: WiggleInterval[]
  rowEvents: Map<number, WiggleEvt[]>
  presentTopicsByRow: Map<number, Set<string>>
  xs: number[]
  MAX_MOVE_TOPICS: number
  MAX_SWAPS_PER_TOPIC: number
  MIN_ROW_TOPICS_TO_EDIT: number
}): Map<number, string[]> {
  const {
    baseOrder,
    intervals,
    rowEvents,
    presentTopicsByRow,
    xs,
    MAX_MOVE_TOPICS,
    MAX_SWAPS_PER_TOPIC,
    MIN_ROW_TOPICS_TO_EDIT,
  } = params

  const rowOrder = new Map<number, string[]>()
  xs.forEach((id) => rowOrder.set(id, baseOrder))

  for (const itv of intervals) {
    const plan = deriveIntervalPlan({
      baseOrder,
      intervalRows: itv.rows,
      rowEvents,
      presentTopicsByRow,
      MAX_MOVE_TOPICS,
      MAX_SWAPS_PER_TOPIC,
      MIN_ROW_TOPICS_TO_EDIT,
    })

    const itv2 = expandIntervalByCoPresence({
      itv,
      moveTopics: plan.moveTopics,
      presentTopicsByRow,
      xs,
    })

    for (const id of itv2.rows) rowOrder.set(id, plan.order)
  }

  return rowOrder
}

function rebuildBandsByRowOrder(params: {
  xs: number[]
  topics: string[]
  rowProfile: Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>
  widthByTopicById: Map<string, Map<number, number>>
  rowOrderMap: Map<number, string[]>
  MIN_WIDTH: number
  MIN_ROW_TOPICS_TO_EDIT: number
}): { topicBands2: Map<string, Segment[]>; topicBandById2: Map<string, Map<number, Segment>> } {
  const {
    xs,
    topics,
    rowProfile,
    widthByTopicById,
    rowOrderMap,
    MIN_WIDTH,
    MIN_ROW_TOPICS_TO_EDIT,
  } = params

  const topicBands2 = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands2.set(t, []))

  const prevLeft2 = new Map<string, number>()

  xs.forEach((id) => {
    const rp = rowProfile.get(id)
    if (!rp) return
    const L = rp.stripLeft
    const R = rp.stripRight
    const stripW = Math.max(0, R - L)

    const pres: { topic: string; width: number }[] = []
    for (const t of topics) {
      const w = widthByTopicById.get(t)!.get(id) ?? 0
      if (w > MIN_WIDTH) pres.push({ topic: t, width: w })
    }
    if (!pres.length) return

    const presSet = new Set(pres.map((p) => p.topic))
    const order = (rowOrderMap.get(id) ?? topics).filter((t) => presSet.has(t))

    if (order.length < MIN_ROW_TOPICS_TO_EDIT) {
      let cursor = L
      for (const t of order) {
        const w = widthByTopicById.get(t)!.get(id) ?? 0
        const left = cursor
        const right = cursor + w
        topicBands2.get(t)!.push({ id, left, right, width: w })
        prevLeft2.set(t, left)
        cursor = right
      }
      const keep = new Set(order)
      for (const t of Array.from(prevLeft2.keys())) if (!keep.has(t)) prevLeft2.delete(t)
      return
    }

    const desiredArr: number[] = []
    const widthArr: number[] = []
    for (let i = 0; i < order.length; i++) {
      const t = order[i]
      const w = widthByTopicById.get(t)!.get(id) ?? 0
      widthArr.push(w)

      const pl = prevLeft2.get(t)
      if (pl != null) desiredArr.push(pl)
      else {
        const frac = order.length === 1 ? 0.5 : i / (order.length - 1)
        const center = L + frac * stripW
        desiredArr.push(center - w / 2)
      }
    }

    // ✅ 这里直接用你现有的 layoutMinMove（方案A同款）
    const lefts = layoutMinMove(desiredArr, widthArr, L, R)

    for (let i = 0; i < order.length; i++) {
      const t = order[i]
      const left = lefts[i]
      const w = widthArr[i]
      const right = left + w
      topicBands2.get(t)!.push({ id, left, right, width: w })
      prevLeft2.set(t, left)
    }

    const keep = new Set(order)
    for (const t of Array.from(prevLeft2.keys())) if (!keep.has(t)) prevLeft2.delete(t)
  })

  const topicBandById2 = buildTopicBandById(topicBands2)
  return { topicBands2, topicBandById2 }
}

// ==============================
// ✅ 对外统一入口：主组件只调用这个
// ==============================
export function applyWiggleSecondPass(p: WiggleSecondPassParams): WiggleSecondPassResult {
  const {
    ENABLE_WIGGLE_SECOND_PASS,
    allPoints,
    xs,
    topics,
    rowProfile,
    widthByTopicById,
    topicBands,
    topicBandById,
    fixedXInTopicRow,
    MIN_WIDTH,

    WIGGLE_JUMP_TH = 0.5,
    WIGGLE_GAP = 1,
    MAX_MOVE_TOPICS = 4,
    MAX_SWAPS_PER_TOPIC = 2,
    MIN_ROW_TOPICS_TO_EDIT = 2,
    DEBUG_WIGGLE = false,
  } = p

  if (!ENABLE_WIGGLE_SECOND_PASS) return { topicBands, topicBandById }

  const presentTopicsByRow = buildPresentTopicsByRow(xs, topics, widthByTopicById, MIN_WIDTH)
  const { wiggleRows, rowEvents } = detectWiggles({
    allPoints,
    WIGGLE_JUMP_TH,
    rowProfile,
    fixedXInTopicRow,
  })
  const intervals = groupToIntervals(wiggleRows, WIGGLE_GAP)

  if (!intervals.length) return { topicBands, topicBandById }

  const baseOrder = topics.slice()
  const rowOrderMap = buildRowOrderMap({
    baseOrder,
    intervals,
    rowEvents,
    presentTopicsByRow,
    xs,
    MAX_MOVE_TOPICS,
    MAX_SWAPS_PER_TOPIC,
    MIN_ROW_TOPICS_TO_EDIT,
  })

  const rebuilt = rebuildBandsByRowOrder({
    xs,
    topics,
    rowProfile,
    widthByTopicById,
    rowOrderMap,
    MIN_WIDTH,
    MIN_ROW_TOPICS_TO_EDIT,
  })

  if (!DEBUG_WIGGLE) {
    return { topicBands: rebuilt.topicBands2, topicBandById: rebuilt.topicBandById2 }
  }

  // ✅ 更可靠的 changedRows：按“本行 present topics”过滤后再对比
  const changedRows: number[] = []
  xs.forEach((id) => {
    const pres = presentTopicsByRow.get(id) ?? new Set<string>()
    const baseF = baseOrder.filter((t) => pres.has(t))
    const ordF = (rowOrderMap.get(id) ?? baseOrder).filter((t) => pres.has(t))
    if (baseF.join('|') !== ordF.join('|')) changedRows.push(id)
  })

  return {
    topicBands: rebuilt.topicBands2,
    topicBandById: rebuilt.topicBandById2,
    debug: {
      wiggleRowsUniq: Array.from(new Set(wiggleRows)).sort((a, b) => a - b),
      intervals: intervals.map((d) => ({ s: d.s, e: d.e, len: d.rows.length })),
      changedRows,
    },
  }
}

export function computeKDE1D(
  samples: number[],
  xs: number[],
  bandwidth: number,
): { x: number; value: number }[] {
  const n = samples.length
  if (n === 0) return xs.map((x) => ({ x, value: 0 }))

  const h = bandwidth
  const invH = 1 / h
  const values = xs.map((x) => ({ x, value: 0 }))

  // Epanechnikov: K(u)=0.75*(1-u^2) for |u|<=1 else 0
  for (const t of samples) {
    for (const v of values) {
      const u = (v.x - t) * invH
      v.value += Math.exp(-0.5 * u * u)
    }
  }

  // 归一化：1/(n*h)
  const normFactor = 1 / (n * h * Math.sqrt(2 * Math.PI))
  for (const v of values) v.value *= normFactor

  return values
}

export type SlotCluster = {
  topic: string
  clusterIndex: number
  startId: number
  endId: number
  ids: number[]
  length: number
}

export function clusterSlotIdsByTopic(
  slotIdsByTopic: Map<string, Set<number>>,
  gapTol: number = 1,
  minLen: number = 1,
): Record<string, SlotCluster[]> {
  const out: Record<string, SlotCluster[]> = {}

  for (const [topic, idSet] of slotIdsByTopic.entries()) {
    const ids = Array.from(idSet).sort((a, b) => a - b)
    const clusters: SlotCluster[] = []
    if (ids.length === 0) {
      out[topic] = clusters
      continue
    }

    let cur: number[] = [ids[0]]
    for (let i = 1; i < ids.length; i++) {
      const prev = ids[i - 1]
      const now = ids[i]
      if (now - prev <= gapTol) cur.push(now)
      else {
        if (cur.length >= minLen) {
          clusters.push({
            topic,
            clusterIndex: clusters.length,
            startId: cur[0],
            endId: cur[cur.length - 1],
            ids: cur.slice(),
            length: cur.length,
          })
        }
        cur = [now]
      }
    }

    if (cur.length >= minLen) {
      clusters.push({
        topic,
        clusterIndex: clusters.length,
        startId: cur[0],
        endId: cur[cur.length - 1],
        ids: cur.slice(),
        length: cur.length,
      })
    }

    out[topic] = clusters
  }

  return out
}

/** 避让布局：修改 points 内的 _y（原地更新） */
export function resolveY<T extends { _ty: number; _y: number }>(
  points: T[],
  yMin: number,
  yMax: number,
  minGap: number,
) {
  const ps = points.slice().sort((a, b) => a._ty - b._ty)

  let cur = yMin
  for (const d of ps) {
    cur = Math.max(d._ty, cur)
    d._y = cur
    cur += minGap
  }

  const overflow = ps[ps.length - 1]._y - yMax
  if (overflow > 0) {
    for (const d of ps) d._y -= overflow
  }

  for (let i = ps.length - 2; i >= 0; i--) {
    const maxAllowed = ps[i + 1]._y - minGap
    ps[i]._y = Math.min(ps[i]._y, maxAllowed)
  }

  const topOverflow = yMin - ps[0]._y
  if (topOverflow > 0) {
    for (const d of ps) d._y += topOverflow
  }
}

export function highlightTopicBands(selected: Set<string> | null) {
  const bands = d3.selectAll<SVGPathElement, unknown>('path.topic-band')

  bands
    .interrupt()
    .transition()
    .duration(300)
    .ease(d3.easeCubicInOut)
    .attr('fill-opacity', function () {
      const t = d3.select(this).attr('data-topic')
      if (!selected || selected.size === 0) return 0.6
      return selected.has(t) ? 0.6 : 0.2
    })
    .attr('transform', 'translate(0,0) scale(1,1)')
}

export function buildGlobalSpeakerFrac(
  speakers: string[],
  EDGE_PAD = 0.1,
  speakerFracGlobal: Map<string, number>,
) {
  const n = speakers.length
  const lanes: number[] = []

  if (n <= 1) {
    lanes.push(0.5)
  } else if (n === 2) {
    lanes.push(EDGE_PAD, 0.5) // ✅ 你要的：0.1, 0.5
  } else {
    for (let i = 0; i < n; i++) {
      lanes.push(EDGE_PAD + (1 - 2 * EDGE_PAD) * (i / (n - 1)))
    }
  }

  speakers.forEach((sp, i) => {
    speakerFracGlobal.set(sp, lanes[i] ?? 0.5)
  })
}

type Box = { x0: number; x1: number; y0: number; y1: number }
export function intersects(b: Box, placed: Box[]): boolean {
  for (const p of placed) {
    const separated = b.x1 < p.x0 || b.x0 > p.x1 || b.y1 < p.y0 || b.y0 > p.y1
    if (!separated) return true
  }
  return false
}

// (C) 用贪心排布：row1 按 topics 顺序；row>=2 追求 left 接近上一行
export function layoutMinMove(desired: number[], widths: number[], L: number, R: number): number[] {
  const k = desired.length
  const left = new Array(k).fill(0)
  if (k === 0) return left

  // forward pass: no overlap
  left[0] = Math.max(desired[0], L)
  for (let i = 1; i < k; i++) {
    left[i] = Math.max(desired[i], left[i - 1] + widths[i - 1])
  }

  // backward pass: fix overflow
  const end = left[k - 1] + widths[k - 1]
  if (end > R) {
    left[k - 1] = Math.min(left[k - 1], R - widths[k - 1])
    for (let i = k - 2; i >= 0; i--) {
      left[i] = Math.min(left[i], left[i + 1] - widths[i])
    }

    // left bound fix
    if (left[0] < L) {
      const shift = L - left[0]
      for (let i = 0; i < k; i++) left[i] += shift
    }
  }

  return left
}

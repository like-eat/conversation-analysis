// src/utils/Methods.ts
import * as d3 from 'd3'
import type { Conversation, Point, Segment, Slot } from '@/types/index'

/** RowProfile：每个 turnId 对应本行条带总宽度与左右边界 */
export type RowProfile = Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>

/** topic -> (turnId -> width) */
export type WidthByTopicById = Map<string, Map<number, number>>

export type SlotXMap = Map<string, number> // key -> x

/** topic -> {color, values[]} */
export type TopicGroup = Map<string, { color: string; values: { x: number; value: number }[] }>

export function pointKey(p: Pick<Point, 'topic' | 'id' | 'source' | 'slot'>) {
  // 用于唯一定位一个 slot（point）
  return `${p.topic}@@${p.id}@@${(p.source || '').trim()}@@${p.slot || ''}`
}

function overlapLen(a0: number, a1: number, b0: number, b1: number) {
  const x0 = Math.max(a0, b0)
  const x1 = Math.min(a1, b1)
  return Math.max(0, x1 - x0)
}

function permute<T>(arr: T[]): T[][] {
  const res: T[][] = []
  const a = arr.slice()
  const n = a.length
  if (n <= 1) return [a]

  const used = new Array(n).fill(false)
  const cur: T[] = []

  function dfs() {
    if (cur.length === n) {
      res.push(cur.slice())
      return
    }
    for (let i = 0; i < n; i++) {
      if (used[i]) continue
      used[i] = true
      cur.push(a[i])
      dfs()
      cur.pop()
      used[i] = false
    }
  }
  dfs()
  return res
}

type PrevSegMap = Map<string, { left: number; right: number }>
type TopicBandById = Map<string, Map<number, Segment>>

export function spreadSpeakerFracs(
  speakerFracGlobal: Map<string, number>,
  stripWidth: number,
  minGapPx = 14, // 两条线最小间距（像素）
  leftPadPx = 8,
  rightPadPx = 8,
) {
  const items = Array.from(speakerFracGlobal.entries())
    .map(([sp, frac]) => ({ sp, frac }))
    .sort((a, b) => a.frac - b.frac)

  if (items.length <= 1) return

  const xMin = leftPadPx
  const xMax = Math.max(xMin, stripWidth - rightPadPx)
  const minGap = minGapPx

  // frac -> x
  const xs = items.map((d) => xMin + d.frac * (xMax - xMin))

  // forward pass：保证递增且相隔 >= minGap
  for (let i = 1; i < xs.length; i++) {
    xs[i] = Math.max(xs[i], xs[i - 1] + minGap)
  }

  // 如果挤出右边界，整体往回推
  const overflow = xs[xs.length - 1] - xMax
  if (overflow > 0) {
    for (let i = 0; i < xs.length; i++) xs[i] -= overflow

    // 再做一次 backward pass，防止左边界被推穿
    for (let i = xs.length - 2; i >= 0; i--) {
      xs[i] = Math.min(xs[i], xs[i + 1] - minGap)
    }
  }

  // x -> frac 写回
  for (let i = 0; i < items.length; i++) {
    const frac = (xs[i] - xMin) / (xMax - xMin + 1e-9)
    speakerFracGlobal.set(items[i].sp, Math.max(0, Math.min(1, frac)))
  }
}

export function solveBandsAndSlotsRowWise(args: {
  // order/rows
  xs: number[]
  topics: string[] // 全局 base 顺序（第一行用这个）
  allPoints: Point[] // 所有 slots（point.id 是 turnId）

  // geometry
  rowProfile: RowProfile
  stripCenter: number
  slotPadX?: number

  // widths
  widthByTopicById: WidthByTopicById
  minWidth?: number

  // speaker lanes (for first appearance targetX)
  speakerFracGlobal: Map<string, number>
  edgeFallbackFrac?: number // speaker 没有 frac 时用

  // objective
  beta?: number // score = A - beta * B - gamma * C
  gamma?: number // 顺序变化惩罚
}) {
  const {
    xs,
    topics,
    allPoints,
    rowProfile,
    widthByTopicById,
    speakerFracGlobal,
    slotPadX = 12,
    minWidth = 1,
    edgeFallbackFrac = 0.5,
    beta = 1.0,
    gamma = 50,
  } = args

  // 输出：topic -> Segment[]
  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  // 输出：每个 point 的 x
  const slotXMap: SlotXMap = new Map()

  // prev row segments，用于 A（同 topic 跨行重叠）
  let prevSeg: PrevSegMap = new Map()

  // prev row final order，用于 C（顺序变化惩罚）
  let prevPerm: string[] | null = null

  // speaker 上一次出现的 x，用于 B
  const lastXBySpeaker = new Map<string, number>()

  // 预分组：按 turnId 收集 slots
  const pointsByTurn = d3.group(allPoints, (p) => p.id)

  // 逆序对：衡量 curr 相对 prev 的顺序变化程度（越大越“翻”）
  function inversionCount(curr: string[], prev: string[]) {
    const pos = new Map<string, number>()
    prev.forEach((t, i) => pos.set(t, i))
    let inv = 0
    for (let i = 0; i < curr.length; i++) {
      for (let j = i + 1; j < curr.length; j++) {
        const pi = pos.get(curr[i])
        const pj = pos.get(curr[j])
        if (pi == null || pj == null) continue
        if (pi > pj) inv++
      }
    }
    return inv
  }

  // [NEW] build perm: fix new topics at their base-order slots, permute only old topics
  function buildPermFixNew(
    basePresent: string[], // topics.filter(widthMap.has)
    newSet: Set<string>,
    oldPerm: string[], // permutation of old topics only
  ) {
    const out: string[] = []
    let k = 0
    for (const t of basePresent) {
      if (newSet.has(t))
        out.push(t) // new topic: fixed position (baseOrder slot)
      else out.push(oldPerm[k++]) // old topic: fill remaining slots by permutation
    }
    return out
  }

  for (let rowIdx = 0; rowIdx < xs.length; rowIdx++) {
    const turnId = xs[rowIdx]
    const rp = rowProfile.get(turnId)
    if (!rp) continue

    const L = rp.stripLeft
    const R = rp.stripRight
    const W = R - L

    // 本行出现的 topics（width>minWidth）
    const presentTopics: string[] = []
    const widthMap = new Map<string, number>()
    for (const t of topics) {
      const w = widthByTopicById.get(t)?.get(turnId) ?? 0
      if (w > minWidth) {
        presentTopics.push(t)
        widthMap.set(t, w)
      }
    }

    if (presentTopics.length === 0) {
      prevSeg = new Map()
      prevPerm = null
      continue
    }

    // 本行 slots
    const rowSlots = pointsByTurn.get(turnId) ?? []

    // base-present list in global order (used as "slot template")
    const basePresent = topics.filter((t) => widthMap.has(t))

    // identify new/old topics (new topic = not in prevSeg)
    const oldTopics = presentTopics.filter((t) => prevSeg.has(t))
    const newTopics = presentTopics.filter((t) => !prevSeg.has(t))
    const newSet = new Set<string>(newTopics)
    const hasNew = newTopics.length > 0

    // ---------- 候选排列 ----------
    let permList: string[][] = []
    if (rowIdx === 0) {
      // 第一行：严格按 topics 的 base 顺序
      permList = [basePresent]
    } else {
      if (hasNew) {
        // ✅ fix new topics at base slots; only permute old topics
        if (oldTopics.length <= 1) {
          permList = [basePresent]
        } else {
          const oldPermList = permute(oldTopics)
          permList = oldPermList.map((oldPerm) => buildPermFixNew(basePresent, newSet, oldPerm))
        }
      } else {
        // no new topics: keep original behavior
        permList = permute(presentTopics)
      }
    }

    // ---------- eval：给定 perm + shift -> score / segs / slotXs ----------
    function evalOne(perm: string[], shift: number) {
      // packed segments
      const segThis: PrevSegMap = new Map()
      let cursor = L + shift
      for (const t of perm) {
        const w = widthMap.get(t) ?? 0
        const left = cursor
        const right = cursor + w
        segThis.set(t, { left, right })
        cursor = right
      }

      // A: overlap with prev row same topic
      let A = 0
      segThis.forEach((seg, t) => {
        const p = prevSeg.get(t)
        if (!p) return
        A += overlapLen(seg.left, seg.right, p.left, p.right)
      })

      // B: slot movement cost
      let B = 0
      const slotXsLocal: Array<{ key: string; x: number; speaker: string }> = []

      for (const p of rowSlots) {
        const t = p.topic
        const seg = segThis.get(t)
        if (!seg) continue

        const sp = (p.source || '').trim()
        const frac = speakerFracGlobal.get(sp) ?? edgeFallbackFrac

        // first appearance => lane target; else use last x
        const targetX = lastXBySpeaker.get(sp) ?? L + frac * W

        const minX = seg.left + slotPadX
        const maxX = seg.right - slotPadX
        const x = maxX <= minX ? (seg.left + seg.right) / 2 : clamp(targetX, minX, maxX)

        B += Math.abs(x - targetX)
        slotXsLocal.push({ key: pointKey(p), x, speaker: sp })
      }

      // C: order change penalty (relative to prevPerm, on common topics)
      let C = 0
      if (prevPerm && prevPerm.length > 1) {
        const prevCommon = prevPerm.filter((t) => widthMap.has(t))
        if (prevCommon.length > 1) {
          C = inversionCount(perm, prevCommon)
        }
      }

      // const score = A

      // const score = A - beta * B

      const score = A - beta * B - gamma * C
      return { score, segThis, slotXsLocal, A, B, C }
    }

    // ---------- shift candidates ----------
    const sumW = d3.sum(Array.from(widthMap.values()))
    const slack = W - sumW

    if (slack < 0) {
      // 极端情况：本行总宽超过 strip（理论上不该发生）
      const perm = permList[0]
      const { segThis, slotXsLocal } = evalOne(perm, 0)

      segThis.forEach((seg, t) => {
        topicBands.get(t)!.push({
          id: turnId,
          left: seg.left,
          right: seg.right,
          width: seg.right - seg.left,
        })
      })

      for (const s of slotXsLocal) slotXMap.set(s.key, s.x)
      for (const s of slotXsLocal) lastXBySpeaker.set(s.speaker, s.x)

      prevSeg = segThis
      prevPerm = perm
      continue
    }

    const shiftCandidates = new Set<number>()
    shiftCandidates.add(0)
    shiftCandidates.add(slack)
    shiftCandidates.add(slack / 2)

    // ---------- 搜索最优 perm + shift ----------
    let bestScore = -Infinity
    let bestSeg: PrevSegMap | null = null
    let bestSlotXs: Array<{ key: string; x: number; speaker: string }> = []
    let bestPerm: string[] | null = null

    for (const perm of permList) {
      for (const s of shiftCandidates) {
        const shift = clamp(s, 0, slack)
        const out = evalOne(perm, shift)
        if (out.score > bestScore) {
          bestScore = out.score
          bestSeg = out.segThis
          bestSlotXs = out.slotXsLocal
          bestPerm = perm
        }
      }
    }

    if (!bestSeg || !bestPerm) continue

    // ---------- 写入输出 ----------
    bestSeg.forEach((seg, t) => {
      topicBands.get(t)!.push({
        id: turnId,
        left: seg.left,
        right: seg.right,
        width: seg.right - seg.left,
      })
    })

    for (const s of bestSlotXs) slotXMap.set(s.key, s.x)
    for (const s of bestSlotXs) lastXBySpeaker.set(s.speaker, s.x)

    prevSeg = bestSeg
    prevPerm = bestPerm
  }

  return { topicBands, slotXMap }
}

/**
 * 1D KDE（Gaussian kernel）
 * - samples: 观测点（turnId 列表）
 * - xs: 评估位置（全局 turnId 轴）
 * - bandwidth: 带宽（h）
 */
export function computeKDE1D(
  samples: number[],
  xs: number[],
  bandwidth: number,
): { x: number; value: number }[] {
  const n = samples.length
  if (n === 0) return xs.map((x) => ({ x, value: 0 }))

  // 防御：避免 h=0 导致 NaN/Infinity
  const h = Math.max(1e-6, bandwidth)
  const invH = 1 / h

  const values = xs.map((x) => ({ x, value: 0 }))

  // Gaussian kernel: exp(-0.5*u^2)
  for (const t of samples) {
    for (const v of values) {
      const u = (v.x - t) * invH
      v.value += Math.exp(-0.5 * u * u)
    }
  }

  // 归一化：1/(n*h*sqrt(2π))
  // const normFactor = 1 / (n * h * Math.sqrt(2 * Math.PI))
  // for (const v of values) v.value *= normFactor

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
  if (!points.length) return

  const ps = points.slice().sort((a, b) => a._ty - b._ty)

  let cur = yMin
  for (const d of ps) {
    cur = Math.max(d._ty, cur)
    d._y = cur
    cur += minGap
  }

  // 下溢出：整体上移
  const overflow = ps[ps.length - 1]._y - yMax
  if (overflow > 0) {
    for (const d of ps) d._y -= overflow
  }

  // 从下往上再压一遍，确保 gap
  for (let i = ps.length - 2; i >= 0; i--) {
    const maxAllowed = ps[i + 1]._y - minGap
    ps[i]._y = Math.min(ps[i]._y, maxAllowed)
  }

  // 上溢出：整体下移
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

/**
 * speakers -> 全局列比例（0..1）
 * 注意：n=2 时建议左右各占一列（EDGE_PAD 与 1-EDGE_PAD），避免第二个 speaker 被放在中心导致“挤在一起”
 */
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
    lanes.push(EDGE_PAD, 1 - EDGE_PAD) // ✅ 更合理：左右两列
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

// ---- A) clamp score 到 [min,max] ----
export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}

// ---- B) 从 Conversation[] 抽 points + topics + colorMap ----
export function extractPointsAndTopics(
  dataArr: Conversation[],
  scoreMap: Map<number, number>,
  topicColorMapRef: Record<string, string>,
) {
  const points: Point[] = []
  const topicsSet = new Set<string>()
  const slotIdsByTopic = new Map<string, Set<number>>()

  dataArr.forEach((conv) => {
    const topic = conv.topic ?? 'Unknown Topic'
    const slots = conv.slots ?? []

    topicsSet.add(topic)

    // 防御：conv.color 可能为空；别把 undefined 写进 map
    if (conv.color) topicColorMapRef[topic] = conv.color
    else if (!topicColorMapRef[topic]) topicColorMapRef[topic] = '#999'

    if (!slotIdsByTopic.has(topic)) slotIdsByTopic.set(topic, new Set<number>())

    slots.forEach((s) => {
      if (typeof s.id !== 'number') return
      slotIdsByTopic.get(topic)!.add(s.id)

      const speakerName = (s.source || 'Unknown').toString().trim()
      const score = scoreMap.get(s.id) ?? 0.5

      points.push({
        topic,
        slot: s.slot ?? '未标注 Slot',
        id: s.id,
        topicColor: conv.color || topicColorMapRef[topic] || '#1f77b4',
        source: speakerName,
        sentence: s.sentence,
        is_question: !!s.is_question,
        resolved: !!s.resolved,
        info_score: score,
        wordcloud: (s as Slot).wordcloud ?? [],
      })
    })
  })

  const topics = Array.from(topicsSet)
  return { points, topics, slotIdsByTopic }
}

// ---- C) 为 speakers 分配颜色 ----
export function assignSpeakerColors(
  points: Point[],
  speakerColorMapRef: Record<string, string>,
  palette: string[],
) {
  const speakers = Array.from(new Set(points.map((p) => p.source).filter((n) => !!n)))
  speakers.sort()

  speakers.forEach((name, idx) => {
    if (!speakerColorMapRef[name]) speakerColorMapRef[name] = palette[idx % palette.length]
  })
  return speakers
}

// ---- D) 计算全局时间范围 xs ----
export function computeXs(points: Point[]) {
  const globalMinTurn = d3.min(points, (d) => d.id) ?? 0
  const globalMaxTurn = d3.max(points, (d) => d.id) ?? 0
  const xs = d3.range(globalMinTurn, globalMaxTurn + 1)
  return { globalMinTurn, globalMaxTurn, xs }
}

// ---- E) KDE：按 topic 得到密度曲线 ----
// ✅ 修复点：不要强迫外部再传一次 computeKDE1D；默认使用本文件的 computeKDE1D
export function computeTopicKDE(
  points: Point[],
  topics: string[],
  xs: number[],
  kdeFn: (
    ids: number[],
    xs: number[],
    bandwidth: number,
  ) => { x: number; value: number }[] = computeKDE1D,
) {
  const topicGroup: TopicGroup = new Map()

  const totalSteps = xs.length
  const BANDWIDTH = Math.max(6, Math.round(totalSteps / 50))

  const nested = d3.group(points, (d) => d.topic)
  nested.forEach((arr, topic) => {
    const topicColor = arr[0]?.topicColor || '#1f77b4'
    const ids = Array.from(new Set(arr.map((d) => d.id))).sort((a, b) => a - b)
    const values = kdeFn(ids, xs, BANDWIDTH)
    topicGroup.set(topic, { color: topicColor, values })
  })

  // 防御：确保 topics 都在 map 里
  topics.forEach((t) => {
    if (!topicGroup.has(t))
      topicGroup.set(t, { color: '#999', values: xs.map((x) => ({ x, value: 0 })) })
  })

  return { topicGroup, totalSteps }
}

// ---- F) 计算每行总条带宽度 rowProfile（block 平滑）----
export function buildRowProfile(args: {
  xs: number[]
  turnScoreMap: Map<number, number>
  numBlocks: number
  stripWidthFixed: number
  stripCenter: number
  minF?: number
  maxF?: number
  gamma?: number
  useSmooth?: boolean
}) {
  const {
    xs,
    turnScoreMap,
    numBlocks,
    stripWidthFixed,
    stripCenter,
    minF = 0.2,
    maxF = 1.0,
    gamma = 1.5,
    useSmooth = true,
  } = args

  const totalSteps = xs.length
  const safeBlocks = Math.max(1, Math.min(numBlocks, totalSteps)) // 防御：blocks 不要 > totalSteps
  const BLOCK_SIZE = Math.ceil(totalSteps / safeBlocks)

  // 1) 每块平均 score
  const blockAvgScore: number[] = new Array(safeBlocks).fill(NaN)
  for (let bi = 0; bi < safeBlocks; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    let sum = 0
    let cnt = 0
    for (const id of blockIds) {
      const s = clamp(turnScoreMap.get(id) ?? 0.6, 0.2, 1)
      if (Number.isFinite(s)) {
        sum += s
        cnt++
      }
    }
    blockAvgScore[bi] = cnt ? sum / cnt : NaN
  }

  // 2) 全局 min/max（用于归一化）
  const valid = blockAvgScore.filter(Number.isFinite) as number[]
  const bMin = valid.length ? Math.min(...valid) : 0.2
  const bMax = valid.length ? Math.max(...valid) : 1.0

  // 3) avgScore -> factor
  function scoreToFactor(avgScore: number) {
    if (!(bMax > bMin)) return (minF + maxF) / 2
    const s = clamp(avgScore, 0.2, 1)
    const t = (s - bMin) / (bMax - bMin)
    const t2 = Math.pow(clamp(t, 0, 1), gamma)
    return minF + (maxF - minF) * t2
  }

  const blockFactor = blockAvgScore.map((s) =>
    Number.isFinite(s) ? scoreToFactor(s) : (minF + maxF) / 2,
  )

  // 4) 下采样 / 平滑：把 blockFactor 分配到每一行
  const rowProfile: RowProfile = new Map()
  for (let bi = 0; bi < safeBlocks; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    const cur = blockFactor[bi]
    const next = blockFactor[Math.min(bi + 1, safeBlocks - 1)]
    const L = blockIds.length

    for (let k = 0; k < L; k++) {
      const id = blockIds[k]

      let factor = cur
      if (useSmooth) {
        const t = L <= 1 ? 0 : k / (L - 1)
        const tt = t * t * (3 - 2 * t)
        factor = cur + (next - cur) * tt
      }

      const rowWidth = stripWidthFixed * factor
      const half = rowWidth / 2
      rowProfile.set(id, {
        rowWidth,
        stripLeft: stripCenter - half,
        stripRight: stripCenter + half,
      })
    }
  }

  return rowProfile
}

// ---- F) 计算每行总条带宽度 rowProfile（block 平滑）----
export function buildRowProfileKDE(args: {
  xs: number[]
  turnScoreMap: Map<number, number>
  numBlocks: number
  stripCenter: number
  pxPerScore: number
  minRowWidth?: number
  useSmooth?: boolean
}) {
  const {
    xs,
    turnScoreMap,
    numBlocks,
    stripCenter,
    pxPerScore,
    minRowWidth = 0,
    useSmooth = true,
  } = args

  const totalSteps = xs.length
  const safeBlocks = Math.max(1, Math.min(numBlocks, totalSteps))
  const BLOCK_SIZE = Math.ceil(totalSteps / safeBlocks)

  // ✅ [NEW] 统计：有多少行被 minRowWidth 主导
  let dominatedCnt = 0
  let validCnt = 0
  let minRaw = Infinity,
    maxRaw = -Infinity // 可选：看 s 的范围

  // 1) 每块平均 raw score
  const blockAvgScore: number[] = new Array(safeBlocks).fill(NaN)
  for (let bi = 0; bi < safeBlocks; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)

    let sum = 0
    let cnt = 0
    for (const id of blockIds) {
      const s = turnScoreMap.get(id)
      if (Number.isFinite(s)) {
        const ss = Math.max(0, s!)
        sum += ss
        cnt++

        // ✅ [NEW] 统计 raw s 范围（可选）
        minRaw = Math.min(minRaw, ss)
        maxRaw = Math.max(maxRaw, ss)
      }
    }
    blockAvgScore[bi] = cnt ? sum / cnt : NaN
  }

  // 2) 下采样 / 平滑：把 blockAvgScore 分配到每一行
  const rowProfile: RowProfile = new Map()
  for (let bi = 0; bi < safeBlocks; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    const cur = Number.isFinite(blockAvgScore[bi]) ? blockAvgScore[bi] : 0
    const next = Number.isFinite(blockAvgScore[Math.min(bi + 1, safeBlocks - 1)])
      ? blockAvgScore[Math.min(bi + 1, safeBlocks - 1)]
      : cur

    const L = blockIds.length

    for (let k = 0; k < L; k++) {
      const id = blockIds[k]

      let s = cur
      if (useSmooth) {
        const t = L <= 1 ? 0 : k / (L - 1)
        const tt = t * t * (3 - 2 * t)
        s = cur + (next - cur) * tt
      }

      const rawW = s * pxPerScore

      // ✅ [NEW] dominated 统计：rawW 是否被 minRowWidth 压住
      validCnt++
      if (rawW < minRowWidth) dominatedCnt++

      const rowWidth = Math.max(minRowWidth, rawW)
      const half = rowWidth / 2

      rowProfile.set(id, {
        rowWidth,
        stripLeft: stripCenter - half,
        stripRight: stripCenter + half,
      })
    }
  }

  // ✅ [NEW] 打印统计结果（只打印一次）
  console.log(
    `[RowProfile] dominated=${dominatedCnt}/${validCnt} (${((dominatedCnt / Math.max(1, validCnt)) * 100).toFixed(1)}%)`,
    `rawS=[${isFinite(minRaw) ? minRaw.toExponential(2) : 'NA'}, ${isFinite(maxRaw) ? maxRaw.toExponential(2) : 'NA'}]`,
    `pxPerScore=${pxPerScore}, minRowWidth=${minRowWidth}`,
  )

  return rowProfile
}

// ---- G) topic 在每行的宽度：按 KDE 比例分配 ----
export function computeWidthByTopicById(args: {
  topics: string[]
  xs: number[]
  rowProfile: RowProfile
  topicGroup: TopicGroup
  alpha?: number
  relDensTh?: number // 新增：相对密度阈值
  minWidthPx?: number // 新增：像素阈值
  minRatio?: number // 新增：比例阈值
}) {
  const {
    topics,
    xs,
    rowProfile,
    topicGroup,
    alpha = 2,
    relDensTh = 0.02,
    minWidthPx = 1,
    minRatio = 0.01,
  } = args

  const widthByTopicById: WidthByTopicById = new Map()
  topics.forEach((t) => widthByTopicById.set(t, new Map()))

  xs.forEach((id, idx) => {
    const rp = rowProfile.get(id)
    if (!rp) return
    const localWidth = rp.rowWidth

    const densities = topics.map((t) => topicGroup.get(t)?.values[idx]?.value ?? 0)
    const maxD = d3.max(densities) ?? 0

    // 1) 先按相对密度砍尾巴
    const dens2 = densities.map((v) => (maxD > 0 && v < maxD * relDensTh ? 0 : v))

    // 2) 权重
    const weighted = dens2.map((v) => (v > 0 ? Math.pow(v, alpha) : 0))
    const sumW = d3.sum(weighted)
    if (sumW <= 0) return

    // 3) 原始宽度
    const rawW = weighted.map((w) => (w / sumW) * localWidth)

    // 4) 二次砍：像素/比例都太小就置 0
    const cut = rawW.map((w) => (w < minWidthPx || w / localWidth < minRatio ? 0 : w))
    const sumCut = d3.sum(cut)
    if (sumCut <= 0) return

    topics.forEach((t, ti) => {
      const w = cut[ti]
      if (w > 0) widthByTopicById.get(t)!.set(id, (w / sumCut) * localWidth)
    })
  })

  return widthByTopicById
}

// ---- H) 固定顺序 cursor：生成 topicBands ----
export function buildTopicBandsFixedOrder(args: {
  topics: string[]
  xs: number[]
  rowProfile: RowProfile
  widthByTopicById: WidthByTopicById
  minWidth?: number
}) {
  const { topics, xs, rowProfile, widthByTopicById, minWidth = 1 } = args

  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  xs.forEach((id) => {
    const rp = rowProfile.get(id)
    if (!rp) return

    let cursor = rp.stripLeft

    for (const t of topics) {
      const w = widthByTopicById.get(t)!.get(id) ?? 0
      if (w <= minWidth) continue

      const left = cursor
      const right = cursor + w
      topicBands.get(t)!.push({ id, left, right, width: w })
      cursor = right
    }
  })

  return topicBands
}

// ---- I) topicBands -> topicBandById（便于按 turn 查左右边界）----
// Segment: { id: number; left: number; right: number; width?: number; ... }
// topicBands: Map<string, Segment[]>

export function buildTopicBandById(
  topicBands: Map<string, Segment[]>,
  minKeepWidth = 0, // <10 的不保存
) {
  const out = new Map<string, Map<number, Segment>>()

  topicBands.forEach((segs, topic) => {
    const byId = new Map<number, Segment>()

    for (const s of segs) {
      const L = Math.min(s.left, s.right)
      const R = Math.max(s.left, s.right)
      const w = Math.max(0, R - L)

      // 关键：太细就“清空”——即不写入 byId
      if (w < minKeepWidth) continue

      byId.set(s.id, { ...s, left: L, right: R, width: w })
    }

    out.set(topic, byId)
  })

  return out
}

// ---- J) 全局 outline path（用于 clipPath 兜底）----
export function computeOutlinePath(args: {
  rowProfile: RowProfile
  yScaleTime: d3.ScaleLinear<number, number>
}) {
  const { rowProfile, yScaleTime } = args
  if (rowProfile.size === 0) return null

  const ids = Array.from(rowProfile.keys()).sort((a, b) => a - b)

  // 采样点数（避免 path 太重）
  const MAX_POINTS = 30
  const STEP = Math.max(1, Math.floor(ids.length / MAX_POINTS))

  const sampled: number[] = []
  for (let i = 0; i < ids.length; i += STEP) sampled.push(ids[i])
  if (sampled[sampled.length - 1] !== ids[ids.length - 1]) sampled.push(ids[ids.length - 1])

  const leftEdge: [number, number][] = sampled.map((id) => [
    rowProfile.get(id)!.stripLeft,
    yScaleTime(id),
  ])
  const rightEdge: [number, number][] = sampled
    .slice()
    .reverse()
    .map((id) => [rowProfile.get(id)!.stripRight, yScaleTime(id)])

  const outlineLine = d3
    .line<[number, number]>()
    .x((p) => p[0])
    .y((p) => p[1])
    .curve(d3.curveCatmullRom.alpha(0.5))

  return outlineLine([...leftEdge, ...rightEdge, leftEdge[0]]) ?? null
}

// ---- K) 生成 fixedXInTopicRow：按 speaker 全局列比例放点 ----
export function makeFixedXInTopicRow(args: {
  topicBandById: Map<string, Map<number, Segment>>
  speakerFracGlobal: Map<string, number>
  stripCenter: number
  slotPadX?: number
}) {
  const { topicBandById, speakerFracGlobal, stripCenter, slotPadX = 12 } = args

  return function fixedXInTopicRow(topic: string, p: Point) {
    const seg = topicBandById.get(topic)?.get(p.id)
    if (!seg) return stripCenter

    const sp = (p.source || '').trim()
    const frac = speakerFracGlobal.get(sp) ?? 0.5

    const minX = seg.left + slotPadX
    const maxX = seg.right - slotPadX
    if (maxX <= minX) return (seg.left + seg.right) / 2

    const x = minX + frac * (maxX - minX)
    return clamp(x, minX, maxX)
  }
}

export function pruneTopicBands(topicBands: Map<string, Segment[]>, minKeepWidth = 0) {
  const out = new Map<string, Segment[]>()

  topicBands.forEach((segs, topic) => {
    const pruned = segs
      .map((s) => {
        const L = Math.min(s.left, s.right)
        const R = Math.max(s.left, s.right)
        const w = Math.max(0, R - L)
        return { ...s, left: L, right: R, width: w }
      })
      .filter((s) => (s.width ?? 0) >= minKeepWidth)

    out.set(topic, pruned)
  })

  return out
}

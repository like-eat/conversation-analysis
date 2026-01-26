<template>
  <div class="capsule-container">
    <div ref="UIcontainer" class="capsule-body"></div>

    <div class="dataset-label">
      {{ datasetName }}
    </div>

    <!-- 操作按钮 -->
    <button class="bottom-left-btn" @click="DeleteLine">清除线条</button>
    <button class="bottom-mid-btn" @click="AddTalk">新开分支</button>
    <button class="bottom-right-btn" @click="emit('toggle-dataset')">切换数据</button>
  </div>
</template>

<script setup lang="ts">
//  1) 依赖 / 类型
import * as d3 from 'd3'
import { ref, watch, computed } from 'vue'
import type { Conversation, MessageItem, Point, Segment, Slot } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'
import {
  computeKDE1D,
  resolveY,
  highlightTopicBands,
  buildGlobalSpeakerFrac,
  intersects,
  layoutMinMove,
  applyWiggleSecondPass,
} from '@/utils/Methods'

type PointWithLayout = Point & {
  _x: number
  _y: number
  _ty: number
}

const datasetName = computed(() => {
  return props.datasetKey === 'meeting' ? '情感综艺' : '心理疾病'
})

//  2) 全局 Store / 响应式状态
const FileStore = useFileStore()

const UIcontainer = ref<HTMLElement | null>(null)
const activeTopicKey = ref<string | null>(null)
const activeTopics = ref<Set<string>>(new Set())

// 存储对话数据（渲染输入）
const data = ref<Conversation[]>([])

// 选中 topic 后，用于“新开分支”的上下文
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

// turn id -> 信息量评分（影响条带宽度）
const turnScoreMap = new Map<number, number>()

//  3) 配置项 / 颜色映射
// topic -> 颜色（由数据文件给定）
const topicColorMap: Record<string, string> = {}

// speaker -> 颜色（本地分配）
const speakerColorMap: Record<string, string> = {}

// 每个发言人一个颜色
const SPEAKER_PALETTE = ['#14B8A6', '#C026D3', '#A3E635', '#FB7185', '#0F172A']

//  4) Props / Emits（切换数据集）
type DatasetKey = 'meeting' | 'xinli'
const props = defineProps<{ datasetKey: DatasetKey }>()
const emit = defineEmits<{ (e: 'toggle-dataset'): void }>()

const DATASETS: Record<
  DatasetKey,
  {
    convUrl: string
    scoreUrl: string
    stripWidth: number
    num_blocks: number
    ENABLE_MINMOVE_LAYOUT: boolean
    ENABLE_WIGGLE_SECOND_PASS: boolean
  }
> = {
  meeting: {
    convUrl: '/meeting_result.json',
    scoreUrl: '/meeting_info_with_scores.json',
    stripWidth: 500,
    num_blocks: 10,
    ENABLE_MINMOVE_LAYOUT: true,
    ENABLE_WIGGLE_SECOND_PASS: true,
  },
  xinli: {
    convUrl: '/xinli_result.json',
    scoreUrl: '/xinli_info_with_scores.json',
    stripWidth: 500,
    num_blocks: 10,
    ENABLE_MINMOVE_LAYOUT: true,
    ENABLE_WIGGLE_SECOND_PASS: true,
  },
}

//  5) 交互回调 / 按钮逻辑
const onSlotClick = (slotId: number) => {
  FileStore.selectedSlotId = slotId
}

// 清空 UI 数据（你的逻辑里用于“新开分支”时清画面）
const clearUI = () => {
  data.value = []
}

// 新开分支：把当前选中的 topic 的内容塞进 FileStore 作为上下文
const AddTalk = () => {
  if (!selectedTopicMessages.value.length) {
    console.log('请先点击一个 topic！')
    return
  }

  // 一、清除绘制内容
  clearUI()
  FileStore.triggerRefresh()

  // 二、将选中的 topic 内容作为历史上下文
  const history = selectedTopicMessages.value.map((m) => ({
    id: m.id,
    from: m.role,
    text: m.content,
  })) as MessageItem[]
  FileStore.setMessageContent(history)
}

// 清除 slot 连线（只删 path，不删文本/圆点）
const DeleteLine = () => {
  d3.selectAll('.speaker-global-line').remove()
}

//  6) 加载数据并绘制
async function loadAndDraw(key: DatasetKey) {
  const {
    convUrl,
    scoreUrl,
    stripWidth,
    num_blocks,
    ENABLE_MINMOVE_LAYOUT,
    ENABLE_WIGGLE_SECOND_PASS,
  } = DATASETS[key]

  const convResp = await fetch(convUrl)
  const convJson: Conversation[] = await convResp.json()

  const scoreResp = await fetch(scoreUrl)
  const scoreJson: Array<{ id: number; info_score: number }> = await scoreResp.json()

  // 写入分数映射
  turnScoreMap.clear()
  scoreJson.forEach((item) => turnScoreMap.set(item.id, item.info_score))

  // （建议）切换数据时清掉旧的颜色/高亮状态，避免残留
  activeTopicKey.value = null
  activeTopics.value.clear()
  selectedTopicMessages.value = []

  Object.keys(topicColorMap).forEach((k) => delete topicColorMap[k])
  Object.keys(speakerColorMap).forEach((k) => delete speakerColorMap[k])

  data.value = convJson
  drawUI(
    convJson,
    turnScoreMap,
    stripWidth,
    num_blocks,
    ENABLE_MINMOVE_LAYOUT,
    ENABLE_WIGGLE_SECOND_PASS,
  )
}

//  7) 绘制主 UI（KDE 条带 + 图例 + slot 云 + lens）
function drawUI(
  dataArr: Conversation[],
  turnScoreMap: Map<number, number>,
  STRIP_WIDTH_FIXED: number,
  NUM_WIDTH_BLOCKS: number,
  ENABLE_MINMOVE_LAYOUT: boolean,
  ENABLE_WIGGLE_SECOND_PASS: boolean,
) {
  if (!UIcontainer.value) return

  // 清空画布
  d3.select(UIcontainer.value).selectAll('*').remove()

  // ===== 额外：slot lens（局部放大镜）=====
  let wordcloudTurn: number | null = null

  // [新增] 保存总条带外轮廓 path（用于 clipPath 裁剪 slot 云）
  let outlinePathDataForClip: string | null = null

  // ===== 1) 抽点：Conversation[] -> points[] =====
  const points: Point[] = []
  const topicsSet = new Set<string>()
  const slotIdsByTopic = new Map<string, Set<number>>()

  dataArr.forEach((conv) => {
    const topic = conv.topic ?? 'Unknown Topic'
    const slots = conv.slots ?? []

    topicsSet.add(topic)
    topicColorMap[topic] = conv.color

    // ✅ 确保这个 topic 的 Set 被创建
    if (!slotIdsByTopic.has(topic)) slotIdsByTopic.set(topic, new Set<number>())

    slots.forEach((s) => {
      if (typeof s.id !== 'number') return

      slotIdsByTopic.get(topic)!.add(s.id)

      const speakerName = (s.source || 'Unknown').toString().trim()
      const score = turnScoreMap.get(s.id) ?? 0.5

      points.push({
        topic,
        slot: s.slot ?? '未标注 Slot',
        id: s.id,
        topicColor: conv.color || '#1f77b4',
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

  // ===== 2) 发言人颜色分配 =====
  const speakers = Array.from(new Set(points.map((p) => p.source).filter((name) => !!name)))
  speakers.sort()

  speakers.forEach((name, idx) => {
    if (!speakerColorMap[name]) {
      const color = SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length]
      speakerColorMap[name] = color
    }
  })

  const allPoints = points

  // 全局时间范围（按 id）
  const globalMinTurn = d3.min(points, (d) => d.id) ?? 0
  const globalMaxTurn = d3.max(points, (d) => d.id) ?? 0
  const xs = d3.range(globalMinTurn, globalMaxTurn + 1)

  // ===== 3) KDE 按 topic 分组 =====
  const topicGroup = new Map<
    string,
    {
      color: string
      values: { x: number; value: number }[]
    }
  >()

  const totalSteps = xs.length
  const BANDWIDTH = Math.max(6, Math.round(totalSteps / 50)) // 100->3~4, 400->10

  const nested = d3.group(points, (d) => d.topic)
  nested.forEach((arr, topic) => {
    const topicColor = arr[0]?.topicColor || '#1f77b4'
    const ids = Array.from(new Set(arr.map((d) => d.id))).sort((a, b) => a - b)
    const values = computeKDE1D(ids, xs, BANDWIDTH)
    topicGroup.set(topic, { color: topicColor, values })
  })

  // ===== 4) 布局参数 =====
  const width = 1000
  const height = 900
  const MARGIN = { top: 20, right: 20, bottom: 30, left: 100 }
  const innerWidth = width - MARGIN.left - MARGIN.right
  const innerHeight = height - MARGIN.top - MARGIN.bottom

  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)
  const contentG = g.append('g').attr('class', 'content-root')
  const bandLayer = contentG.append('g').attr('class', 'band-layer') // 画条带
  const overlayLayer = contentG.append('g').attr('class', 'overlay-layer') // 画线/slot

  // y 轴：按 turn id 映射到像素
  const yScaleTime = d3.scaleLinear().domain([globalMinTurn, globalMaxTurn]).range([0, innerHeight])
  const yAxis = d3.axisLeft(yScaleTime).ticks(10).tickFormat(d3.format('d'))

  g.append('g')
    .attr('class', 'axis y-axis')
    .call(yAxis as d3.Axis<number>)

  g.append('text')
    .attr('class', 'axis-label')
    .attr('x', 0)
    .attr('y', innerHeight / 2)
    .attr('text-anchor', 'middle')
    .attr('transform', `rotate(-90, -40, ${innerHeight / 2})`)
    .attr('fill', '#555')
    .attr('font-size', 12)
    .text('时间（对话轮次）')

  // 条带位置
  const STRIP_WIDTH = STRIP_WIDTH_FIXED
  const STRIP_CENTER = innerWidth / 2 // ✅ 中心固定
  const STRIP_LEFT = STRIP_CENTER - STRIP_WIDTH / 2

  // ===== 5) 生成“每一行总条带宽度” profile（按 block 平滑）=====
  const BLOCK_SIZE = Math.ceil(totalSteps / NUM_WIDTH_BLOCKS)

  // 每行的宽度和范围
  const rowProfile = new Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>()

  const MIN_F = 0.2 // 最小宽度比例
  const MAX_F = 1 // 最大宽度比例
  const GAMMA = 1.5 // ✅ 调大差异：1.5~4 都可以试

  // clamp score 到 [0.2,1]
  function clampScore(score: number) {
    return Math.max(0.2, Math.min(1, score))
  }

  function syncSlotClouds() {
    // 根容器：专门装多个 topic 的云
    let root = overlayLayer.select<SVGGElement>('.slot-global-cloud-root')
    if (root.empty()) root = overlayLayer.append('g').attr('class', 'slot-global-cloud-root')

    // 先删掉不在 activeTopics 的 layer
    root.selectAll<SVGGElement, unknown>('g.slot-global-cloud-topic').each(function () {
      const t = d3.select(this).attr('data-topic') || ''
      if (!activeTopics.value.has(t)) d3.select(this).remove()
    })

    // 再确保 activeTopics 里的 topic 都渲染出来
    activeTopics.value.forEach((topic) => {
      let layer = root.select<SVGGElement>(`g.slot-global-cloud-topic[data-topic="${topic}"]`)
      if (layer.empty()) {
        layer = root.append('g').attr('class', 'slot-global-cloud-topic').attr('data-topic', topic)
      }
      showSlotCloudInto(topic, layer) // 👈 用“渲染到指定layer”的版本
    })

    root.raise()
  }

  // ===== (1) 先算：每个 block 的 avgScore（不是 avgFactor）=====
  const blockAvgScore: number[] = new Array(NUM_WIDTH_BLOCKS).fill(NaN)

  for (let bi = 0; bi < NUM_WIDTH_BLOCKS; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    let sum = 0
    let cnt = 0
    for (const id of blockIds) {
      const s = clampScore(turnScoreMap.get(id) ?? 0.6)
      if (Number.isFinite(s)) {
        sum += s
        cnt++
      }
    }
    blockAvgScore[bi] = cnt ? sum / cnt : NaN
  }

  // ===== (2) 对 blockAvgScore 做“全局归一化 + gamma”映射到 [MIN_F,MAX_F] =====
  const valid = blockAvgScore.filter(Number.isFinite) as number[]
  const bMin = valid.length ? Math.min(...valid) : 0.2
  const bMax = valid.length ? Math.max(...valid) : 1.0

  function blockScoreToFactor(avgScore: number) {
    // 如果所有块均值一样，避免除 0：直接给中值
    if (!(bMax > bMin)) return (MIN_F + MAX_F) / 2

    const s = clampScore(avgScore)
    const t = (s - bMin) / (bMax - bMin) // 0..1（块级全局拉伸）
    const t2 = Math.pow(Math.max(0, Math.min(1, t)), GAMMA)
    return MIN_F + (MAX_F - MIN_F) * t2
  }

  const blockFactor: number[] = blockAvgScore.map((s) =>
    Number.isFinite(s) ? blockScoreToFactor(s) : (MIN_F + MAX_F) / 2,
  )

  // ===== (3) 把 blockFactor 应用到每一行：可选平滑 or 阶梯 =====
  const USE_SMOOTH = true // 想看“块差异”就设 false

  for (let bi = 0; bi < NUM_WIDTH_BLOCKS; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    const cur = blockFactor[bi]
    const nextIdx = Math.min(bi + 1, NUM_WIDTH_BLOCKS - 1)
    const next = blockFactor[nextIdx]

    const L = blockIds.length
    for (let k = 0; k < L; k++) {
      const id = blockIds[k]

      let factor = cur
      if (USE_SMOOTH) {
        const t = L <= 1 ? 0 : k / (L - 1)
        const tt = t * t * (3 - 2 * t) // smoothstep
        factor = cur + (next - cur) * tt
      }

      const rowWidth = STRIP_WIDTH * factor
      const halfWidth = rowWidth / 2
      const stripLeft = STRIP_CENTER - halfWidth
      const stripRight = STRIP_CENTER + halfWidth

      rowProfile.set(id, { rowWidth, stripLeft, stripRight })
    }
  }

  // ===== 6) 每个 topic 的条带几何（每行分配宽度）=====
  let topicBands = new Map<string, Segment[]>()

  const widthByTopicById = new Map<string, Map<number, number>>() // topic -> (id -> width)

  topics.forEach((t) => {
    topicBands.set(t, [])
    widthByTopicById.set(t, new Map())
  })

  xs.forEach((id, idx) => {
    const rp = rowProfile.get(id)
    if (!rp) return

    const localWidth = rp.rowWidth

    const densities = topics.map((t) => topicGroup.get(t)!.values[idx]?.value ?? 0)
    const sumDensity = d3.sum(densities)
    if (!sumDensity || sumDensity <= 0) return

    const ALPHA = 2
    const DENS_EPS = 1e-7
    let weighted = densities.map((v) => (v > DENS_EPS ? Math.pow(v, ALPHA) : 0))
    let sumWeighted = d3.sum(weighted)

    if (!sumWeighted || sumWeighted <= 0) {
      weighted = topics.map(() => 1)
      sumWeighted = topics.length
    }

    topics.forEach((topic, ti) => {
      const wv = weighted[ti]
      if (wv <= 0) return

      const wTopic = (wv / sumWeighted) * localWidth
      widthByTopicById.get(topic)!.set(id, wTopic)
    })
  })

  // 你可以调：过滤“极细但导致永远算出现”的条带
  const MIN_WIDTH = 1 // 条带最小宽度
  const prevLeft = new Map<string, number>() // topic -> prev row left

  xs.forEach((id, rowIdx) => {
    const rp = rowProfile.get(id)
    if (!rp) return

    // 取出这行的宽度范围
    const L = rp.stripLeft
    const R = rp.stripRight
    const stripW = Math.max(0, R - L)

    // 筛出“本行真正出现的 topics
    const present: { topic: string; width: number }[] = []
    for (const t of topics) {
      const w = widthByTopicById.get(t)!.get(id) ?? 0
      if (w > MIN_WIDTH) present.push({ topic: t, width: w })
    }
    if (present.length === 0) return

    // ===== A OFF: baseline —— 每行按 topics 固定顺序 cursor 排 =====
    if (!ENABLE_MINMOVE_LAYOUT) {
      let cursor = L
      for (const t of topics) {
        const hit = present.find((p) => p.topic === t)
        if (!hit) continue
        const left = cursor
        const right = cursor + hit.width
        topicBands.get(t)!.push({ id, left, right, width: hit.width })
        cursor = right
      }
      return
    }

    // --- Row 1：按 topics 顺序（但只摆 present 的）---
    if (rowIdx === 0) {
      let cursor = L
      // 保持 topics 顺序：按 topics 过滤 present
      for (const t of topics) {
        const hit = present.find((p) => p.topic === t)
        if (!hit) continue
        const left = cursor
        const right = cursor + hit.width
        topicBands.get(t)!.push({ id, left, right, width: hit.width })
        prevLeft.set(t, left)
        cursor = right
      }
      return
    }

    // --- Row >=2：贪心目标：同 topic left 尽量接近上一行 ---
    const oldOnes: { topic: string; width: number; desired: number }[] = []
    const newOnes: { topic: string; width: number; desired: number }[] = []

    // old 的 desired 就是上一行的 left
    for (const p of present) {
      const pl = prevLeft.get(p.topic)
      if (pl != null) oldOnes.push({ ...p, desired: pl })
      else newOnes.push({ ...p, desired: 0 })
    }

    // 给 newOnes 分配 desired
    if (newOnes.length > 0) {
      // 宽度从大到小排序
      newOnes.sort((a, b) => b.width - a.width)
      for (let i = 0; i < newOnes.length; i++) {
        const frac = newOnes.length === 1 ? 0.5 : i / (newOnes.length - 1)
        // 均匀散开，这时候会有重叠，后面消除
        const center = L + frac * stripW
        newOnes[i].desired = center - newOnes[i].width / 2
      }
    }

    // 将想要的位置合并排序
    const items = [...oldOnes, ...newOnes].sort((a, b) => a.desired - b.desired)

    // 第i个条带的期望位置 & 宽度
    const desiredArr = items.map((it) => it.desired)
    const widthArr = items.map((it) => it.width)

    // 调用布局函数避免重叠和越界
    const lefts = layoutMinMove(desiredArr, widthArr, L, R)

    // 记录下这一行各topic的id, left, right, width
    for (let i = 0; i < items.length; i++) {
      const t = items[i].topic
      const left = lefts[i]
      const right = left + items[i].width
      topicBands.get(t)!.push({ id, left, right, width: items[i].width })
      prevLeft.set(t, left)
    }

    // 把这行没出现过的topic且在pre中的，删除掉
    const presentSet = new Set(present.map((x) => x.topic))
    for (const t of Array.from(prevLeft.keys())) {
      if (!presentSet.has(t)) prevLeft.delete(t)
    }
  })

  // topic -> (turnId -> {left,right})
  let topicBandById = new Map<string, Map<number, Segment>>()
  topicBands.forEach((segs, topic) => {
    const m = new Map<number, Segment>()
    segs.forEach((s) => m.set(s.id, s))
    topicBandById.set(topic, m)
  })

  // ===== [NEW] 全局固定：speaker -> frac（不再按 topic） =====
  const speakerFracGlobal = new Map<string, number>()

  // 你前面已经有 speakers 数组，并且 speakers.sort() 过了
  buildGlobalSpeakerFrac(speakers, 0.1, speakerFracGlobal)

  // ===== slot 的 x：根据 “该topic该行band左右边界” + “speaker全局固定列比例” =====
  const SLOT_PAD_X = 12
  function fixedXInTopicRow(topic: string, p: Point): number {
    const seg = topicBandById.get(topic)?.get(p.id)
    if (!seg) return STRIP_CENTER

    const sp = (p.source || '').trim()
    const frac = speakerFracGlobal.get(sp) ?? 0.5

    const minX = seg.left + SLOT_PAD_X
    const maxX = seg.right - SLOT_PAD_X

    // 太窄：直接放中间（或你也可以选择不画这个点）
    if (maxX <= minX) return (seg.left + seg.right) / 2

    const x = minX + frac * (maxX - minX)

    // 最后再保险 clamp 一次
    return Math.max(minX, Math.min(maxX, x))
  }

  // ==============================
  // 第二步 摆动调整
  // ==============================

  if (ENABLE_WIGGLE_SECOND_PASS) {
    const res = applyWiggleSecondPass({
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
      DEBUG_WIGGLE: true, // 想看日志就开
    })

    topicBands = res.topicBands
    topicBandById = res.topicBandById

    if (res.debug) {
      console.log('[B] 触发摆动的行(去重后)=', res.debug.wiggleRowsUniq)
      console.log('[B] 摆动行聚成的区间=', res.debug.intervals)
      console.log('[B] 被修改顺序的行=', res.debug.changedRows)
      console.log('[B] 被修改顺序的行数=', res.debug.changedRows.length)
    }
  }

  // 支持多选
  const selectedTopics = new Set<string>() // 存储被选中的 topics
  let isShiftPressed = false
  // 监听 Shift 键按下
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Shift') {
      isShiftPressed = true
    }
  })

  // 监听 Shift 键松开
  window.addEventListener('keyup', (event) => {
    if (event.key === 'Shift') {
      isShiftPressed = false
    }
  })

  // 选中某个 topic 时，更新 selectedTopicMessages
  const updateSelectedTopic = (topic: string) => {
    const msgs = dataArr
      .filter((c) => c.topic === topic)
      .flatMap((c) =>
        (c.slots || []).map((s) => ({
          id: s.id,
          role: s.source,
          content: s.sentence,
        })),
      )

    // 如果按住 Shift 键，添加或移除 topic
    if (isShiftPressed) {
      if (selectedTopics.has(topic)) {
        selectedTopics.delete(topic) // 已选中则移除
      } else {
        selectedTopics.add(topic) // 否则添加
      }
    } else {
      // 如果没有按 Shift 键，则清空已有选中，仅选中当前 topic
      selectedTopics.clear()
      selectedTopics.add(topic)
    }

    selectedTopicMessages.value = msgs
    highlightSelectedTopics() // 调用高亮多个 topic
  }
  // 高亮选中的所有 topics
  function highlightSelectedTopics() {
    highlightTopicBands(selectedTopics) // 高亮所有选中的 topics
  }

  let wordcloudAnchor: { id: number; x: number; y: number } | null = null
  let zoomK = 1
  const WORDCLOUD_ZOOM_THRESHOLD = 1.5

  function tryRenderWordcloudInBand() {
    let wcLayer = contentG.select<SVGGElement>('.slot-wordcloud-inband')
    if (wcLayer.empty()) wcLayer = contentG.append('g').attr('class', 'slot-wordcloud-inband')
    wcLayer.selectAll('*').remove()

    // 条件：选中 topic + 缩放 >= 阈值 + 已点过某个 slot
    if (!activeTopicKey.value) return
    if (zoomK < WORDCLOUD_ZOOM_THRESHOLD) return
    const targetId = wordcloudTurn
    if (!targetId) return

    const hit = allPoints.find((p) => p.id === targetId && p.topic === activeTopicKey.value)
    const wc = hit?.wordcloud ?? []
    if (!wc.length) return

    const rp = rowProfile.get(targetId)
    if (!rp) return

    // 词云区域：严格限定在该 turn 的条带内
    const PAD = 8
    const boxX0 = rp.stripLeft + PAD
    const boxX1 = rp.stripRight - PAD

    const centerY = yScaleTime(targetId)
    const boxH = 100
    const boxY0 = Math.max(0, centerY - boxH / 2)
    const boxY1 = Math.min(innerHeight, centerY + boxH / 2)

    const boxW = Math.max(10, boxX1 - boxX0)
    const boxH2 = Math.max(10, boxY1 - boxY0)

    // 前 N 个词，按权重降序（权重越大越先放）
    const MAX_WC = 30
    const words = wc
      .slice()
      .filter((d) => d.word)
      .sort((a, b) => (Number(b.weight) || 0) - (Number(a.weight) || 0))
      .slice(0, MAX_WC)

    const wArr = words.map((d) => (Number.isFinite(d.weight) ? d.weight : 0.5))
    let wMin = d3.min(wArr) ?? 0
    let wMax = d3.max(wArr) ?? 1
    if (wMax - wMin < 0.15) {
      wMin = Math.max(0, wMin - 0.4)
      wMax = Math.min(1, wMax + 0.4)
    }

    const sizeScale = d3.scalePow().exponent(1.9).domain([wMin, wMax]).range([8, 26]).clamp(true)
    const alphaScale = d3.scaleLinear().domain([wMin, wMax]).range([0.35, 1.0]).clamp(true)

    // 碰撞放置：更像词云（不是一行一行）
    type Box = { x0: number; x1: number; y0: number; y1: number }
    const placed: Box[] = []

    const baseCx = boxX0 + boxW / 2
    const baseCy = boxY0 + boxH2 / 2

    // 如果有锚点且是当前 turn，就用 slot 的 x（和可选 y）
    const useAnchor = wordcloudAnchor && wordcloudAnchor.id === targetId

    const margin = 14 // 给词云中心留点安全距离
    const cx0 = useAnchor
      ? Math.max(boxX0 + margin, Math.min(boxX1 - margin, wordcloudAnchor!.x))
      : baseCx

    // y 我建议仍用 turn 的 centerY（更稳定）；你也可以用 anchor.y
    const cy0 = baseCy

    const aspectY = Math.max(1.2, (boxH2 / boxW) * 3.2)

    const jitterX = (v: number) => v + (Math.random() - 0.5) * 8
    const jitterY = (v: number) => v + (Math.random() - 0.5) * 14

    const MAX_TRIES = 260
    const PAD2 = 3

    for (const it of words) {
      const w = it.word
      const weight = Number.isFinite(it.weight) ? it.weight : 0.5
      const fs = sizeScale(weight)

      const t = wcLayer
        .append('text')
        .attr('x', 0)
        .attr('y', 0)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#fff')
        .attr('font-family', 'SimHei')
        .attr('font-size', fs)
        .attr('fill-opacity', alphaScale(weight))
        .attr('font-weight', weight > (wMin + wMax) / 2 ? 700 : 400)
        .text(w)

      const node = t.node() as SVGTextElement | null
      if (!node) {
        t.remove()
        continue
      }

      const tw = node.getComputedTextLength()
      const th = fs * 1.05
      const rot = Math.random() < 0.28 ? (Math.random() < 0.5 ? -22 : 22) : 0

      let ok: { x: number; y: number; box: Box } | null = null

      for (let k = 0; k < MAX_TRIES; k++) {
        const a = 0.45 * k
        const r = 5.2 * Math.sqrt(k)
        const x = jitterX(cx0 + r * Math.cos(a))
        const y = jitterY(cy0 + r * aspectY * Math.sin(a))

        const b: Box = {
          x0: x - tw / 2 - PAD2,
          x1: x + tw / 2 + PAD2,
          y0: y - th / 2 - PAD2,
          y1: y + th / 2 + PAD2,
        }

        if (b.x0 < boxX0 || b.x1 > boxX1 || b.y0 < boxY0 || b.y1 > boxY1) continue
        if (intersects(b, placed)) continue

        ok = { x, y, box: b }
        break
      }

      if (!ok) {
        t.remove()
        continue
      }

      t.attr('x', ok.x).attr('y', ok.y)
      if (rot !== 0) t.attr('transform', `rotate(${rot}, ${ok.x}, ${ok.y})`)
      placed.push(ok.box)
    }
  }

  let viewT: d3.ZoomTransform = d3.zoomIdentity

  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([1, 6])
    .on('zoom', (event) => {
      const t = event.transform
      zoomK = t.k

      const anchorX = STRIP_CENTER
      const anchorY = wordcloudTurn ? yScaleTime(wordcloudTurn) : innerHeight / 2

      const srcType = event.sourceEvent?.type

      if (srcType === 'wheel') {
        const x = viewT.x + (viewT.k - t.k) * anchorX
        const y = viewT.y + (viewT.k - t.k) * anchorY
        viewT = d3.zoomIdentity.translate(x, y).scale(t.k)
      } else {
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k ?? t.k)
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k)
      }

      contentG.attr('transform', `translate(${viewT.x},${viewT.y}) scale(${viewT.k})`)

      tryRenderWordcloudInBand()
    })

  svg.call(zoom)

  // ===== 7) 图例布局参数 =====
  const legendWidth = 150
  const legendItemHeight = 18
  const legendPadding = 10

  const topicLegendHeight = legendPadding * 2 + (1 + topics.length) * legendItemHeight

  const roleLegendWidth = 130
  const roleLegendRows = 2
  const roleLegendHeight = legendPadding * 2 + (1 + roleLegendRows) * legendItemHeight

  const SVG_W = width
  const LEGEND_MARGIN_RIGHT = 10
  const LEGEND_GAP_Y = 12

  const topicLegendX = SVG_W - MARGIN.left - legendWidth - LEGEND_MARGIN_RIGHT
  const topicLegendY = 0

  const roleLegendX = topicLegendX
  const roleLegendY = topicLegendY + topicLegendHeight + LEGEND_GAP_Y

  // 全局连线函数
  function drawGlobalSpeakerLines() {
    let globalLineLayer = overlayLayer.select<SVGGElement>('.speaker-global-line-layer')
    if (globalLineLayer.empty()) {
      globalLineLayer = overlayLayer.append('g').attr('class', 'speaker-global-line-layer')
    }
    globalLineLayer.selectAll('*').remove()

    const allWL: PointWithLayout[] = allPoints.map((p) => {
      const ty = yScaleTime(p.id)
      const x = fixedXInTopicRow(p.topic, p)
      return { ...p, _ty: ty, _y: ty, _x: x }
    })

    const bySpeakerAll = d3.group(allWL, (d) => (d.source || '').trim())

    const lineGen = d3
      .line<[number, number]>()
      .x((p) => p[0])
      .y((p) => p[1])
      .curve(d3.curveMonotoneY)

    bySpeakerAll.forEach((pts, speakerName) => {
      if (!speakerName) return
      if (!pts || pts.length < 2) return

      const sorted = pts.slice().sort((a, b) => a.id - b.id)
      const coords: [number, number][] = sorted.map((d) => [d._x, d._y])

      globalLineLayer
        .append('path')
        .attr('class', 'speaker-global-line')
        .attr('d', lineGen(coords)!)
        .attr('fill', 'none')
        .attr('stroke', speakerColorMap[speakerName] || '#999')
        .attr('stroke-width', 2.2)
        .attr('stroke-opacity', 0.9)
    })

    globalLineLayer.raise()
  }

  drawGlobalSpeakerLines()

  // ===== 8) 全局 slot 云（点击 topic 后显示）=====
  function showSlotCloudInto(
    topic: string,
    cloudLayer: d3.Selection<SVGGElement, unknown, any, unknown>,
  ) {
    const allSlots = allPoints.filter((p) => p.topic === topic).sort((a, b) => a.id - b.id)

    if (!allSlots.length) {
      const emptyLayer = contentG.select<SVGGElement>('.slot-global-cloud')
      if (!emptyLayer.empty()) emptyLayer.style('display', 'none')
      return
    }

    const maxSlots = 40
    const lines = allSlots.slice(0, maxSlots)

    const linesWL: PointWithLayout[] = lines.map((d) => {
      const ty = yScaleTime(d.id)
      return { ...d, _ty: ty, _y: ty, _x: 0 }
    })

    linesWL.forEach((d) => {
      d._x = fixedXInTopicRow(topic, d)
    })

    const bySpeakerCol = d3.group(linesWL, (d) => (d.source || '').trim())
    bySpeakerCol.forEach((arr) => {
      resolveY(arr, 0, innerHeight, 10)
    })

    cloudLayer.selectAll('*').remove()

    const labelLayer = cloudLayer.append('g').attr('class', 'slot-label-layer')

    const defs = g.select('defs').empty() ? g.append('defs') : g.select('defs')

    const safeTopicId = topic.replace(/\s+/g, '-').replace(/[^\w-]/g, '')
    const cloudClipId = `cloud-clip-topic-${safeTopicId}`

    defs.select(`#${cloudClipId}`).remove()

    const bandD = topicBandPathMap.get(topic) ?? ''

    if (bandD) {
      defs
        .append('clipPath')
        .attr('id', cloudClipId)
        .attr('clipPathUnits', 'userSpaceOnUse')
        .append('path')
        .attr('d', bandD)
    } else if (outlinePathDataForClip) {
      defs
        .append('clipPath')
        .attr('id', cloudClipId)
        .attr('clipPathUnits', 'userSpaceOnUse')
        .append('path')
        .attr('d', outlinePathDataForClip)
    } else {
      defs
        .append('clipPath')
        .attr('id', cloudClipId)
        .attr('clipPathUnits', 'userSpaceOnUse')
        .append('rect')
        .attr('x', STRIP_LEFT)
        .attr('y', 0)
        .attr('width', STRIP_WIDTH)
        .attr('height', innerHeight)
    }

    const minFont = 10
    const maxFont = 18
    const minOpacity = 0.35
    const maxOpacity = 1.0

    const slotGroups = labelLayer
      .selectAll<SVGGElement, PointWithLayout>('g.slot-label')
      .data(linesWL)
      .enter()
      .append('g')
      .attr('class', 'slot-label')
      .attr('transform', (d: PointWithLayout) => `translate(${d._x}, ${d._y})`)
      .style('cursor', 'pointer')
      .on('click', (event, d: PointWithLayout) => {
        event.stopPropagation()
        onSlotClick(d.id)

        wordcloudTurn = d.id
        wordcloudAnchor = { id: d.id, x: d._x, y: d._y }
        tryRenderWordcloudInBand()
      })

    slotGroups
      .append('circle')
      .attr('r', 3.5)
      .attr('cx', 0)
      .attr('cy', 0)
      .attr('fill', (d: Point) => speakerColorMap[d.source] || '#999')
      .attr('fill-opacity', (_d: Point, i: number) => {
        const t = linesWL.length <= 1 ? 1 : 1 - i / (linesWL.length - 1)
        return minOpacity + t * (maxOpacity - minOpacity)
      })

    slotGroups
      .append('text')
      .attr('x', 6)
      .attr('y', 0)
      .attr('dominant-baseline', 'middle')
      .attr('fill', '#333')
      .attr('font-family', 'SimHei')
      .attr('font-size', (_d: Point, i: number) => {
        const t = linesWL.length <= 1 ? 1 : 1 - i / (linesWL.length - 1)
        return minFont + t * (maxFont - minFont)
      })
      .attr('fill-opacity', 1)
      .text((d: Point) => (d.is_question && d.resolved ? `${d.slot} ✅️` : d.slot))

    cloudLayer
      .transition()
      .duration(450)
      .ease(d3.easeCubicOut)
      .style('opacity', 1)
      .attr('transform', 'translate(0, 0) scale(1)')

    function resetAll() {
      activeTopics.value.clear()
      highlightTopicBands(null)

      const root = overlayLayer.select<SVGGElement>('.slot-global-cloud-root')
      if (!root.empty()) root.selectAll('*').remove()

      const wcLayer = contentG.select<SVGGElement>('.slot-wordcloud-inband')
      if (!wcLayer.empty()) wcLayer.selectAll('*').remove()
      wordcloudTurn = null
    }
    svg.on('click', resetAll)
  }

  // ===== 9) 总条带边框（outline）=====
  if (rowProfile.size > 0) {
    const idsArray = Array.from(rowProfile.keys()).sort((a, b) => a - b)

    const MAX_POINTS = 30
    const STEP = Math.max(1, Math.floor(idsArray.length / MAX_POINTS))

    const sampledIds: number[] = []
    for (let i = 0; i < idsArray.length; i += STEP) sampledIds.push(idsArray[i])

    if (sampledIds[sampledIds.length - 1] !== idsArray[idsArray.length - 1]) {
      sampledIds.push(idsArray[idsArray.length - 1])
    }

    const leftEdge: [number, number][] = sampledIds.map((id) => {
      const rp = rowProfile.get(id)!
      return [rp.stripLeft, yScaleTime(id)]
    })

    const rightEdge: [number, number][] = sampledIds
      .slice()
      .reverse()
      .map((id) => {
        const rp = rowProfile.get(id)!
        return [rp.stripRight, yScaleTime(id)]
      })

    const outlineLine = d3
      .line<[number, number]>()
      .x((p) => p[0])
      .y((p) => p[1])
      .curve(d3.curveCatmullRom.alpha(0.5))

    const outlinePathData = outlineLine([...leftEdge, ...rightEdge, leftEdge[0]])

    outlinePathDataForClip = outlinePathData ?? null
  }

  // ===== 9.5) [NEW] 存每个 topic band 的 path（用于 clip slot 云）=====
  const topicBandPathMap = new Map<string, string>()

  // ===== 10) 画每个 topic band，并绑定点击事件 =====
  topicBands.forEach((segments, topic) => {
    const color = topicGroup.get(topic)!.color
    const MIN_WIDTH = 1.9 // 最小宽度，小于这个宽度的 segment 忽略掉
    const area = d3
      .area<Segment>()
      .defined((d) => d.width >= MIN_WIDTH)
      .y((d) => yScaleTime(d.id))
      .x0((d) => d.left)
      .x1((d) => d.right)
      .curve(d3.curveBasis)

    const bandPathD = area(segments) ?? ''
    topicBandPathMap.set(topic, bandPathD)

    bandLayer
      .append('path')
      .datum(segments)
      .attr('class', 'topic-band')
      .attr('d', bandPathD)
      .attr('fill', color)
      .attr('fill-opacity', 0.7)
      .attr('data-topic', topic)
      .style('cursor', 'pointer')
      .on('click', (event) => {
        event.stopPropagation()
        console.log('点击 topic：', topic)

        updateSelectedTopic(topic)

        const gNode = g.node() as SVGGElement | null
        if (!gNode) return

        if (isShiftPressed) {
          if (activeTopics.value.has(topic)) activeTopics.value.delete(topic)
          else activeTopics.value.add(topic)
        } else {
          activeTopics.value.clear()
          activeTopics.value.add(topic)
        }

        // ✅ 焦点 topic：用于词云/当前操作
        if (activeTopics.value.has(topic)) {
          activeTopicKey.value = topic
        } else if (activeTopicKey.value === topic) {
          activeTopicKey.value = activeTopics.value.size ? Array.from(activeTopics.value)[0] : null
        }

        syncSlotClouds()
      })
  })

  // ===== 11) 主题图例框 =====
  const topicLegendG = g
    .append('g')
    .attr('class', 'topic-legend')
    .attr('transform', `translate(${topicLegendX}, ${topicLegendY})`)

  topicLegendG
    .append('rect')
    .attr('width', legendWidth)
    .attr('height', topicLegendHeight)
    .attr('rx', 6)
    .attr('ry', 6)
    .attr('fill', 'rgba(255,255,255,0.9)')
    .attr('stroke', '#ccc')

  topicLegendG
    .append('text')
    .attr('x', legendPadding)
    .attr('y', legendPadding + 4)
    .attr('fill', '#333')
    .attr('font-size', 12)
    .attr('font-weight', '600')
    .text('主题图例')

  const legendItems = topicLegendG
    .selectAll('.legend-item')
    .data(topics)
    .enter()
    .append('g')
    .attr('class', 'legend-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 8 + i * legendItemHeight})`,
    )
    .style('cursor', 'pointer')
    .on('click', (event, topic) => {
      event.stopPropagation()
      updateSelectedTopic(topic)
    })

  legendItems
    .append('rect')
    .attr('width', 12)
    .attr('height', 12)
    .attr('rx', 2)
    .attr('ry', 2)
    .attr('fill', (d) => topicColorMap[d])

  legendItems
    .append('text')
    .attr('x', 18)
    .attr('y', 10)
    .attr('fill', '#333')
    .attr('font-size', 12)
    .text((d) => d)

  // ===== 12) 角色图例框 =====
  const roleLegendG = g
    .append('g')
    .attr('class', 'role-legend')
    .attr('transform', `translate(${roleLegendX}, ${roleLegendY})`)

  roleLegendG
    .append('rect')
    .attr('width', roleLegendWidth)
    .attr('height', roleLegendHeight)
    .attr('rx', 6)
    .attr('ry', 6)
    .attr('fill', 'rgba(255,255,255,0.9)')
    .attr('stroke', '#ccc')

  roleLegendG
    .append('text')
    .attr('x', legendPadding)
    .attr('y', legendPadding + 4)
    .attr('fill', '#333')
    .attr('font-size', 12)
    .attr('font-weight', '600')
    .text('角色图例')

  const speakerLegendItems = roleLegendG
    .selectAll('.speaker-legend-item')
    .data(speakers)
    .enter()
    .append('g')
    .attr('class', 'speaker-legend-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 8 + i * legendItemHeight})`,
    )

  speakerLegendItems
    .append('circle')
    .attr('cx', 6)
    .attr('cy', 6)
    .attr('r', 5)
    .attr('fill', (name) => speakerColorMap[name] || '#999')

  speakerLegendItems
    .append('text')
    .attr('x', 18)
    .attr('y', 10)
    .attr('fill', '#333')
    .attr('font-size', 11)
    .text((name) => name)
}

//  9) 监听：外部数据变化
watch(
  () => FileStore.GPTContent,
  (content) => {
    console.log(typeof content)
    try {
      content = content.flat()
      console.log('content:', content)
    } catch (err) {
      console.error('JSON 解析失败:', err)
    }
  },
  { immediate: true },
)

// 监听数据集切换：加载并绘制
watch(
  () => props.datasetKey,
  (key) => {
    loadAndDraw(key).catch((e) => console.error('加载可视化数据失败：', e))
  },
  { immediate: true },
)
</script>

<style scoped>
.capsule-container {
  display: flex;
  flex-direction: column;
  position: relative;
  height: 100vh;
}

/* 主画布 */
.capsule-body {
  width: 1000px;
  height: 900px;
  margin-top: 10px;
}

.dataset-label {
  width: 1000px;
  height: 0px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-left: 100px;
  font-size: 28px;
  font-weight: 600;
  color: #111;
  letter-spacing: 2px;
  user-select: none;
}

/* 底部按钮 */
.bottom-left-btn {
  position: absolute;
  bottom: 10px;
  right: 70%;
  transform: translateX(-70%);
  padding: 10px 20px;
  border: none;
  border-radius: 9999px;
  background-color: #007bff;
  color: white;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
  z-index: 10;
}
.bottom-left-btn:hover {
  background-color: #0056b3;
}

.bottom-mid-btn {
  position: absolute;
  bottom: 10px;
  right: 40%;
  transform: translateX(-40%);
  padding: 10px 20px;
  border: none;
  border-radius: 9999px;
  background-color: #007bff;
  color: white;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
  z-index: 10;
}
.bottom-mid-btn:hover {
  background-color: #0056b3;
}

.bottom-right-btn {
  position: absolute;
  bottom: 10px;
  right: 10%;
  transform: translateX(-10%);
  padding: 10px 20px;
  border: none;
  border-radius: 9999px;
  background-color: #007bff;
  color: white;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
  z-index: 10;
}
.bottom-right-btn:hover {
  background-color: #0056b3;
}
</style>

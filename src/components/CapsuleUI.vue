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
// -----------------------------
// 1) 依赖 / 类型
// -----------------------------
import * as d3 from 'd3'
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import type { Conversation, MessageItem, Point, Segment } from '@/types/index'
import type { SlotXMap } from '@/utils/Methods'
import { useFileStore } from '@/stores/FileInfo'

// utils：你已经外提到 Methods.ts 的函数 + 你原本 Methods.ts 里的工具
import {
  extractPointsAndTopics,
  assignSpeakerColors,
  computeXs,
  computeTopicKDE,
  buildRowProfile,
  computeWidthByTopicById,
  // buildTopicBandsFixedOrder,
  buildTopicBandById,
  computeOutlinePath,
  // makeFixedXInTopicRow,
  buildGlobalSpeakerFrac,
  resolveY,
  highlightTopicBands,
  intersects,
  solveBandsAndSlotsRowWise,
  pointKey,
  pruneTopicBands,
  buildTopicBandsFixedOrder,
  makeFixedXInTopicRow,
} from '@/utils/Methods'

function applySpeakerFilter(ctx: DrawCtx) {
  const sp = ctx.activeSpeakerKey

  const lineSel = d3.selectAll<SVGPathElement, unknown>('path.speaker-global-line')

  if (!sp) {
    // 恢复显示
    lineSel.style('display', null)
    return
  }

  // 只显示该 speaker 的全局连线
  lineSel.style('display', function () {
    const name = d3.select(this).attr('data-speaker')
    return name === sp ? null : 'none'
  })
}

function clearSpeakerFilter(ctx: DrawCtx) {
  ctx.activeSpeakerKey = null
  activeSpeakerKey.value = null
  d3.selectAll<SVGPathElement, unknown>('path.speaker-global-line').style('display', null)
}

function hash32(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function mulberry32(seed: number) {
  let a = seed >>> 0
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function shuffleSeeded<T>(arr: T[], seed: number) {
  const a = arr.slice()
  const rnd = mulberry32(seed)
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// baseline 的“很坏排序”：可复现乱序（你也可以换成更坏的 zigzag）
function makeBadTopicOrder(topics: string[], seed: number) {
  return shuffleSeeded(topics, seed)
}

// 你在绘制时给 point 加的 layout 字段
type PointWithLayout = Point & { _x: number; _y: number; _ty: number }

function hashTopicId(topic: string) {
  // djb2 xor hash -> hex string (stable, compact)
  let h = 5381
  for (let i = 0; i < topic.length; i++) h = ((h << 5) + h) ^ topic.charCodeAt(i)
  return (h >>> 0).toString(16)
}

// -----------------------------
// 2) Props / Emits（切换数据集）
// -----------------------------
type DatasetKey = 'meeting' | 'xinli'
const props = defineProps<{ datasetKey: DatasetKey }>()
const emit = defineEmits<{ (e: 'toggle-dataset'): void }>()

// 控制布局优化
const ENABLE_GREEDY_LAYOUT = ref(true)
const BAD_ORDER_SEED = ref(2029)

// -----------------------------
// 3) 组件级状态 / Store
// -----------------------------
const FileStore = useFileStore()

const UIcontainer = ref<HTMLElement | null>(null)

// 当前“焦点 topic”（用于词云/交互逻辑）
const activeTopicKey = ref<string | null>(null)
// 当前“多选 topics”（用于显示多个 slot 云）
const activeTopics = ref<Set<string>>(new Set())

// 当前“焦点 speaker”（用于角色筛选）
const activeSpeakerKey = ref<string | null>(null)

// speaker -> topics set（用于点击角色图例后只显示相关主题）
type SpeakerTopicsMap = Map<string, Set<string>>
function buildSpeakerTopicsIndex(allPoints: Point[]): SpeakerTopicsMap {
  const m: SpeakerTopicsMap = new Map()
  for (const p of allPoints) {
    const sp = (p.source || '').trim()
    if (!sp) continue
    const t = (p.topic ?? 'Unknown Topic') as string
    if (!m.has(sp)) m.set(sp, new Set())
    m.get(sp)!.add(t)
  }
  return m
}

// 存储对话数据（渲染输入）
const data = ref<Conversation[]>([])

// 选中 topic 后，用于“新开分支”的上下文
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

// turn id -> 信息量评分（影响每行总条带宽度）
const turnScoreMap = new Map<number, number>()

// topic -> 颜色（由数据文件给定）
const topicColorMap: Record<string, string> = {}
// speaker -> 颜色（本地分配）
const speakerColorMap: Record<string, string> = {}

// 调色板（发言人颜色）
const SPEAKER_PALETTE = ['#14B8A6', '#C026D3', '#A3E635', '#FB7185', '#0F172A']

// dataset label
const datasetName = computed(() => (props.datasetKey === 'meeting' ? '情感综艺' : '心理疾病'))

// 数据源配置
const DATASETS: Record<
  DatasetKey,
  { convUrl: string; scoreUrl: string; stripWidth: number; num_blocks: number }
> = {
  meeting: {
    convUrl: '/meeting_result.json',
    scoreUrl: '/meeting_info_with_scores.json',
    stripWidth: 500,
    num_blocks: 10,
  },
  xinli: {
    convUrl: '/xinli_result.json',
    scoreUrl: '/xinli_info_with_scores.json',
    stripWidth: 500,
    num_blocks: 10,
  },
}

// -----------------------------
// 4) Shift 多选：只绑定一次（避免 drawUI 重复 addEventListener）
// -----------------------------
const isShiftPressed = ref(false)

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Shift') isShiftPressed.value = true
}
function onKeyUp(e: KeyboardEvent) {
  if (e.key === 'Shift') isShiftPressed.value = false
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
})

// -----------------------------
// 5) UI 按钮逻辑
// -----------------------------
const onSlotClick = (slotId: number) => {
  // 点击 slot 后把选中的 slotId 存到 store（给你后续详情视图/联动用）
  FileStore.selectedSlotId = slotId
}

const clearUI = () => {
  // 你的“新开分支”逻辑：清空当前数据，触发重绘
  data.value = []
}

const AddTalk = () => {
  // 从已选 topic 的消息列表构造 history，交给 store 做后续对话
  if (!selectedTopicMessages.value.length) {
    console.log('请先点击一个 topic！')
    return
  }

  // 1) 清画面
  clearUI()
  FileStore.triggerRefresh()

  // 2) 组装历史上下文
  const history = selectedTopicMessages.value.map((m) => ({
    id: m.id,
    from: m.role,
    text: m.content,
  })) as MessageItem[]

  // 3) 写入 store
  FileStore.setMessageContent(history)
}

const DeleteLine = () => {
  // 只删除全局 speaker 线，不影响其他元素
  d3.selectAll('.speaker-global-line').remove()
}

// -----------------------------
// 6) 数据加载与绘制
// -----------------------------
async function loadAndDraw(key: DatasetKey) {
  // 1) 取该数据集配置
  const { convUrl, scoreUrl, stripWidth, num_blocks } = DATASETS[key]

  // 2) 拉取对话内容
  const convResp = await fetch(convUrl)
  const convJson: Conversation[] = await convResp.json()

  // 3) 拉取每个 turn 的 score
  const scoreResp = await fetch(scoreUrl)
  const scoreJson: Array<{ id: number; info_score: number }> = await scoreResp.json()

  // 4) 写入 score map
  turnScoreMap.clear()
  scoreJson.forEach((item) => turnScoreMap.set(item.id, item.info_score))

  // 5) 切换数据集时清掉旧状态（避免残留）
  activeTopicKey.value = null
  activeTopics.value.clear()
  selectedTopicMessages.value = []
  Object.keys(topicColorMap).forEach((k) => delete topicColorMap[k])
  Object.keys(speakerColorMap).forEach((k) => delete speakerColorMap[k])

  // 6) 更新 data 并绘制
  data.value = convJson
  drawUI(convJson, turnScoreMap, stripWidth, num_blocks)
}

/**
 * ======================================================================
 * 7) drawUI 外提：绘制上下文 ctx（让外部函数无需依赖闭包）
 * ======================================================================
 */
type DrawCtx = {
  // ---- DOM / Layers ----
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>
  g: d3.Selection<SVGGElement, unknown, null, undefined>
  contentG: d3.Selection<SVGGElement, unknown, null, undefined>
  bandLayer: d3.Selection<SVGGElement, unknown, null, undefined>
  overlayLayer: d3.Selection<SVGGElement, unknown, null, undefined>
  defs: d3.Selection<SVGDefsElement, unknown, null, undefined>

  // ---- Geometry ----
  width: number
  height: number
  margin: { top: number; right: number; bottom: number; left: number }
  innerWidth: number
  innerHeight: number
  stripCenter: number
  stripWidthFixed: number
  stripLeftFixed: number

  // ---- Data ----
  dataArr: Conversation[]
  allPoints: Point[]
  topics: string[]
  speakers: string[]
  topicGroup: Map<string, { color: string; values: { x: number; value: number }[] }>
  xs: number[]
  globalMinTurn: number
  globalMaxTurn: number

  // ---- Layout ----
  yScaleTime: d3.ScaleLinear<number, number>
  rowProfile: Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>
  topicBands: Map<string, Segment[]>
  topicBandById: Map<string, Map<number, Segment>>

  slotXMap: SlotXMap

  // ---- Clip paths ----
  outlinePathD: string | null
  topicBandPathMap: Map<string, string>

  // ---- UI session states ----
  selectedTopics: Set<string> // 用于高亮 + AddTalk 上下文
  wordcloudTurn: number | null
  wordcloudAnchor: { id: number; x: number; y: number } | null
  zoomK: number
  // ---- Speaker filter ----
  activeSpeakerKey: string | null
  speakerTopics: SpeakerTopicsMap

  // ---- functions that need access to refs ----
  updateSelectedTopic: () => void
  syncSlotClouds: () => void
  resetAll: () => void
}

/**
 * ======================================================================
 * 8) drawUI 外提：创建 SVG 场景 + 图层
 * ======================================================================
 */
function createScene(
  container: HTMLElement,
  width: number,
  height: number,
  margin: DrawCtx['margin'],
) {
  // 1) 创建 svg
  const svg = d3.select(container).append('svg').attr('width', width).attr('height', height)

  // 2) 根 group：用于留 margin
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

  // 3) 内容 group：缩放/平移只作用在 contentG
  const contentG = g.append('g').attr('class', 'content-root')
  const bandLayer = contentG.append('g').attr('class', 'band-layer')
  const overlayLayer = contentG.append('g').attr('class', 'overlay-layer')

  // 4) defs：clipPath / marker 放这里
  const defs = g.select('defs').empty()
    ? g.append('defs')
    : (g.select('defs') as d3.Selection<SVGDefsElement, unknown, null, undefined>)

  return { svg, g, contentG, bandLayer, overlayLayer, defs }
}

/**
 * ======================================================================
 * 9) drawUI 外提：绘制 y 轴
 * ======================================================================
 */
function drawYAxis(g: DrawCtx['g'], yScaleTime: DrawCtx['yScaleTime'], innerHeight: number) {
  const yAxis = d3.axisLeft(yScaleTime).ticks(10).tickFormat(d3.format('d'))
  g.append('g')
    .attr('class', 'axis y-axis')
    .call(yAxis as d3.Axis<number>)

  // y 轴标题
  g.append('text')
    .attr('class', 'axis-label')
    .attr('x', 0)
    .attr('y', innerHeight / 2)
    .attr('text-anchor', 'middle')
    .attr('transform', `rotate(-90, -40, ${innerHeight / 2})`)
    .attr('fill', '#555')
    .attr('font-size', 12)
    .text('时间（对话轮次）')
}

/**
 * ======================================================================
 * 10) drawUI 外提：全局 speaker 连线
 * ======================================================================
 */
function drawGlobalSpeakerLines(ctx: DrawCtx) {
  let globalLineLayer = ctx.overlayLayer.select<SVGGElement>('.speaker-global-line-layer')
  if (globalLineLayer.empty())
    globalLineLayer = ctx.overlayLayer.append('g').attr('class', 'speaker-global-line-layer')
  globalLineLayer.selectAll('*').remove()

  // 1) 计算每个点布局坐标
  const allWL: PointWithLayout[] = ctx.allPoints.map((p) => {
    const ty = ctx.yScaleTime(p.id)
    // const x = ctx.fixedXInTopicRow(p.topic, p)
    const k = pointKey(p)
    const x = ctx.slotXMap.get(k) ?? ctx.stripCenter

    return { ...p, _ty: ty, _y: ty, _x: x }
  })

  // 2) 按 speaker 分组
  const bySpeakerAll = d3.group(allWL, (d) => (d.source || '').trim())

  // 3) 线生成器
  const lineGen = d3
    .line<[number, number]>()
    .x((p) => p[0])
    .y((p) => p[1])
    .curve(d3.curveMonotoneY)

  // 4) 绘制每条 speaker 线
  bySpeakerAll.forEach((pts, speakerNameRaw) => {
    const speakerName = (speakerNameRaw || '').trim()
    if (!speakerName) return
    if (!pts || pts.length < 2) return

    const sorted = pts.slice().sort((a, b) => a.id - b.id)
    const coords: [number, number][] = sorted.map((d) => [d._x, d._y])

    globalLineLayer
      .append('path')
      .attr('class', 'speaker-global-line')
      .attr('data-speaker', speakerName)
      .attr('d', lineGen(coords)!)
      .attr('fill', 'none')
      .attr('stroke', speakerColorMap[speakerName] || '#999')
      .attr('stroke-width', 2.2)
      .attr('stroke-opacity', 0.9)
  })

  globalLineLayer.raise()
}

/**
 * ======================================================================
 * 11) drawUI 外提：渲染条带（bands），同时缓存每个 topic 的 bandPathD
 * ======================================================================
 */
function renderTopicBands(ctx: DrawCtx) {
  ctx.topicBands.forEach((segments, topic) => {
    const color = ctx.topicGroup.get(topic)!.color

    const MIN_BAND_WIDTH = 0.1
    const area = d3
      .area<Segment>()
      .defined((d) => d.width >= MIN_BAND_WIDTH)
      .y((d) => ctx.yScaleTime(d.id))
      .x0((d) => d.left)
      .x1((d) => d.right)
      .curve(d3.curveBasis)

    // ✅ 关键：补齐所有 turn，缺失的 turn 用 width=0 占位，制造断点
    const byId = new Map<number, Segment>()
    segments.forEach((s) => {
      const L = Math.min(s.left, s.right)
      const R = Math.max(s.left, s.right)
      byId.set(s.id, { ...s, left: L, right: R, width: Math.max(0, R - L) })
    })

    const segsFull: Segment[] = ctx.xs.map((id) => {
      const s = byId.get(id)
      if (s) return s
      // 占位段：会被 defined 过滤，但能让 d3 在这里“断开”
      return { id, left: ctx.stripCenter, right: ctx.stripCenter, width: 0 } as Segment
    })

    const bandPathD = area(segsFull) ?? ''
    ctx.topicBandPathMap.set(topic, bandPathD)

    ctx.bandLayer
      .append('path')
      .datum(segsFull) // ✅ 这里也建议绑定 segsFull（保持一致）
      .attr('class', 'topic-band')
      .attr('d', bandPathD)
      .attr('fill', color)
      .attr('fill-opacity', 0.7)
      .attr('data-topic', topic)
      .style('cursor', 'pointer')
      .on('click', (event) => {
        event.stopPropagation()

        // ✅ 点击 topic 时，退出 speaker 过滤模式
        if (ctx.activeSpeakerKey) clearSpeakerFilter(ctx)

        if (isShiftPressed.value) {
          const next = new Set(activeTopics.value)
          if (next.has(topic)) next.delete(topic)
          else next.add(topic)
          activeTopics.value = next
        } else {
          activeTopics.value = new Set([topic])
        }

        highlightTopicBands(activeTopics.value)

        if (activeTopics.value.has(topic)) {
          activeTopicKey.value = topic
        } else if (activeTopicKey.value === topic) {
          activeTopicKey.value = activeTopics.value.size ? Array.from(activeTopics.value)[0] : null
        }

        ctx.updateSelectedTopic()
        ctx.syncSlotClouds()
      })
  })
}

/**
 * ======================================================================
 * 12) drawUI 外提：slot 云（渲染到指定 layer）
 * ======================================================================
 */
function showSlotCloudInto(
  ctx: DrawCtx,
  topic: string,
  cloudLayer: d3.Selection<SVGGElement, unknown, any, unknown>,
) {
  // 1) 筛出该 topic 所有 points（按时间排序）
  // ✅ 如果当前有 activeSpeakerKey，则只显示该 speaker 的 slots
  const spFilter = ctx.activeSpeakerKey
  const allSlots = ctx.allPoints
    .filter((p) => p.topic === topic)
    .filter((p) => {
      if (!spFilter) return true
      return (p.source || '').trim() === spFilter
    })
    .sort((a, b) => a.id - b.id)

  if (!allSlots.length) return

  // 2) 限制显示数量（避免太重）
  const maxSlots = 40
  const lines = allSlots.slice(0, maxSlots)

  // 3) 初始化布局（y=turn, x=待填）
  const linesWL: PointWithLayout[] = lines.map((d) => {
    const ty = ctx.yScaleTime(d.id)
    return { ...d, _ty: ty, _y: ty, _x: 0 }
  })

  // 4) 计算 x（固定列）
  linesWL.forEach((d) => {
    const k = pointKey(d)

    const x = ctx.slotXMap.get(k)
    d._x = x ?? ctx.stripCenter // 找不到就给个兜底
  })

  // 5) 按 speaker 分列，做 y 方向避让（避免 label 重叠）
  const bySpeakerCol = d3.group(linesWL, (d) => (d.source || '').trim())
  bySpeakerCol.forEach((arr) => resolveY(arr, 0, ctx.innerHeight, 10))

  // 6) 清空该 topic layer
  cloudLayer.selectAll('*').remove()
  const labelLayer = cloudLayer.append('g').attr('class', 'slot-label-layer')

  // 7) clipPath：优先 topic band path；否则 outline；再否则矩形
  const cloudClipId = `cloud-clip-topic-${hashTopicId(topic)}`

  // 8) label 样式参数
  const minFont = 10
  const maxFont = 18
  const minOpacity = 0.35
  const maxOpacity = 1.0

  // 9) 数据绑定（每个 slot 一个 group：circle + text）
  const slotGroups = labelLayer
    .selectAll<SVGGElement, PointWithLayout>('g.slot-label')
    .data(linesWL)
    .enter()
    .append('g')
    .attr('class', 'slot-label')
    .attr('transform', (d) => `translate(${d._x}, ${d._y})`)
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      // 阻止冒泡：避免触发 svg click reset
      event.stopPropagation()

      // 1) 通知 store（查看详情）
      onSlotClick(d.id)

      // 2) 设置词云目标 turn + anchor
      ctx.wordcloudTurn = d.id
      // === anchor 改成“文字中心”而不是点 ===
      const g = event.currentTarget as SVGGElement
      const textNode = g.querySelector('text') as SVGTextElement | null

      // 你的文字是 x=6, text-anchor 默认为 start，所以中心 = 6 + textWidth/2
      const textXLocal = 6
      const textW = textNode ? textNode.getComputedTextLength() : 0

      const anchorX = d._x + textXLocal + textW / 2
      const anchorY = d._y

      ctx.wordcloudAnchor = { id: d.id, x: anchorX, y: anchorY }

      // 3) 重新绘制词云
      tryRenderWordcloudInBandbubble(ctx)
    })

  // 10) 圆点（按 speaker 着色，越早越显眼）
  slotGroups
    .append('circle')
    .attr('r', 3.5)
    .attr('cx', 0)
    .attr('cy', 0)
    .attr('fill', (d) => speakerColorMap[d.source] || '#999')
    .attr('fill-opacity', (_d, i) => {
      const t = linesWL.length <= 1 ? 1 : 1 - i / (linesWL.length - 1)
      return minOpacity + t * (maxOpacity - minOpacity)
    })

  // 11) 文本（按时间映射字号）
  const LEFT_SPEAKERS = new Set<string>(['功必扬']) // 这里填你想放左侧的发言人名字

  slotGroups
    .append('text')
    .attr('x', (d) => {
      const sp = (d.source || '').trim()
      return LEFT_SPEAKERS.has(sp) ? -6 : 6
    })
    .attr('text-anchor', (d) => {
      const sp = (d.source || '').trim()
      return LEFT_SPEAKERS.has(sp) ? 'end' : 'start'
    })
    .attr('y', 0)
    .attr('dominant-baseline', 'middle')
    .attr('fill', '#333')
    .attr('font-family', 'SimHei')
    .attr('font-size', (_d, i) => {
      const t = linesWL.length <= 1 ? 1 : 1 - i / (linesWL.length - 1)
      return minFont + t * (maxFont - minFont)
    })
    .attr('fill-opacity', 1)
    .text((d) => (d.is_question && d.resolved ? `${d.slot} ✅️` : d.slot))

  // 12) clip 到“整条 strip 区域”（推荐）
  cloudLayer.attr('clip-path', null) // 先清掉旧的，避免残留

  ctx.defs.select(`#${cloudClipId}`).remove()

  ctx.defs
    .append('clipPath')
    .attr('id', cloudClipId)
    .attr('clipPathUnits', 'userSpaceOnUse')
    .append('rect')
    .attr('x', ctx.stripLeftFixed)
    .attr('y', 0)
    .attr('width', ctx.stripWidthFixed)
    .attr('height', ctx.innerHeight)

  cloudLayer.attr('clip-path', `url(#${cloudClipId})`)

  // 13) 小动画出现
  cloudLayer
    .transition()
    .duration(450)
    .ease(d3.easeCubicOut)
    .style('opacity', 1)
    .attr('transform', 'translate(0, 0) scale(1)')
}

/**
 * ======================================================================
 * 13) drawUI 外提：同步渲染多个 activeTopics 的 slot 云
 * ======================================================================
 */
function syncSlotClouds(ctx: DrawCtx) {
  // 根容器
  let root = ctx.overlayLayer.select<SVGGElement>('.slot-global-cloud-root')
  if (root.empty()) root = ctx.overlayLayer.append('g').attr('class', 'slot-global-cloud-root')

  // 1) 删除不在 activeTopics 的 layer
  root.selectAll<SVGGElement, unknown>('g.slot-global-cloud-topic').each(function () {
    const t = d3.select(this).attr('data-topic') || ''
    if (!activeTopics.value.has(t)) d3.select(this).remove()
  })

  // 2) 确保每个 active topic 都有一个 layer
  activeTopics.value.forEach((topic) => {
    // 用 node 查找，避免泛型 parent 不一致
    let node: SVGGElement | null = null
    root.selectAll<SVGGElement, unknown>('g.slot-global-cloud-topic').each(function () {
      if (d3.select(this).attr('data-topic') === topic) node = this as SVGGElement
    })

    // 没有就创建
    if (!node) {
      node = root
        .append('g')
        .attr('class', 'slot-global-cloud-topic')
        .attr('data-topic', topic)
        .node() as SVGGElement
    }

    // 用 select(node) 得到稳定 selection（parent 泛型固定为 SVGGElement）
    const layer = d3.select(node)
    showSlotCloudInto(ctx, topic, layer)
  })

  root.raise()
}

/**
 * ======================================================================
 * 14) drawUI 外提：词云渲染（放在条带内部）
 * ======================================================================
 */

function tryRenderWordcloudInBandbubble(ctx: DrawCtx) {
  // === layer ===
  let wcLayer = ctx.contentG.select<SVGGElement>('.slot-wordcloud-bubble')
  if (wcLayer.empty()) wcLayer = ctx.contentG.append('g').attr('class', 'slot-wordcloud-bubble')
  wcLayer.selectAll('*').remove()

  // === conditions ===
  const WORDCLOUD_ZOOM_THRESHOLD = 1
  if (!activeTopicKey.value) return
  if (ctx.zoomK < WORDCLOUD_ZOOM_THRESHOLD) return
  if (!ctx.wordcloudTurn || !ctx.wordcloudAnchor) return

  // === find wordcloud data ===
  const hit = ctx.allPoints.find(
    (p) => p.id === ctx.wordcloudTurn && p.topic === activeTopicKey.value,
  )
  const wc = hit?.wordcloud ?? []
  if (!wc.length) return

  // === seeded random (stable layout per topic+turn) ===
  function mulberry32(seed: number) {
    let a = seed >>> 0
    return function () {
      a |= 0
      a = (a + 0x6d2b79f5) | 0
      let t = Math.imul(a ^ (a >>> 15), 1 | a)
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
  }
  const seedHex = hashTopicId(activeTopicKey.value)
  const seedInt = (parseInt(seedHex.slice(0, 8), 16) ^ (ctx.wordcloudTurn * 2654435761)) >>> 0
  const rnd = mulberry32(seedInt)

  // bubble size & gap
  const bubbleW = 180
  const bubbleH = 120
  const gapX = 12
  const padEdge = 8

  const anchor = ctx.wordcloudAnchor!
  const stripL = ctx.stripLeftFixed
  const stripR = ctx.stripLeftFixed + ctx.stripWidthFixed * 0.8

  const side: 'L' | 'R' = anchor.x < ctx.stripCenter + 40 ? 'L' : 'R'

  // 1) 先给一个“理想位置”：尽量靠近点击点
  let boxX0 =
    side === 'L'
      ? anchor.x - bubbleW - gapX // 左侧：右边缘距点 gapX
      : anchor.x + gapX // 右侧：左边缘距点 gapX

  // 2) 再强制保证“完全在条带外”
  if (side === 'L') {
    // 右边缘 <= stripL - gapX
    boxX0 = Math.min(boxX0, stripL - gapX - bubbleW)
  } else {
    // 左边缘 >= stripR + gapX
    boxX0 = Math.max(boxX0, stripR)
  }

  console.log('anchor.x', anchor.x, 'stripCenter', ctx.stripCenter, 'zoomK', ctx.zoomK)

  // 3) 最后做画布边界 clamp（左右同样需要，但边界不一样）
  if (side === 'L') {
    const minX = padEdge
    const maxX = Math.min(ctx.innerWidth, stripL)
    boxX0 = Math.max(minX, Math.min(maxX, boxX0))
  } else {
    const minX = Math.max(padEdge, stripR + gapX)
    const maxX = ctx.innerWidth
    boxX0 = Math.max(minX, Math.min(maxX, boxX0))
  }

  // 5) y：围绕点击点居中，再 clamp
  let boxY0 = anchor.y - bubbleH / 2
  boxY0 = Math.max(padEdge, Math.min(ctx.innerHeight - bubbleH - padEdge, boxY0))

  const boxX1 = boxX0 + bubbleW
  const boxY1 = boxY0 + bubbleH

  // === bubble background + arrow ===
  const bubbleG = wcLayer.append('g').attr('class', 'bubble')

  // (optional) let clicks pass through bubble; avoid interfering with svg click reset
  bubbleG.style('pointer-events', 'none')

  bubbleG
    .append('rect')
    .attr('x', boxX0)
    .attr('y', boxY0)
    .attr('width', bubbleW)
    .attr('height', bubbleH)
    .attr('rx', 14)
    .attr('ry', 14)
    .attr('fill', 'rgba(255,255,255,0.92)')
    .attr('stroke', '#cfcfcf')
    .attr('stroke-width', 1.2)

  // arrow points to anchor
  // ----- fat curved tail (filled) -----
  // anchor
  // anchor（默认指向圆点）
  let ax = anchor.x
  const ay = anchor.y

  // 仅对“功必扬”：把尾巴目标挪到左侧文本区域
  const sp = (hit?.source || '').trim()
  if (sp === '功必扬') {
    const textDx = 6 // 你画 text 的 x 偏移（LEFT 是 -6，但这里我们用绝对值）
    const estHalfTextW = 60 // 估计“半个文字宽”，按效果调：30~70 都常见
    ax = anchor.x - (textDx + estHalfTextW)
  }

  // base point on bubble edge
  const bx = side === 'L' ? boxX0 + bubbleW : boxX0
  const by = Math.max(boxY0 + 18, Math.min(boxY1 - 18, ay))

  // direction from base -> anchor
  const dx = ax - bx
  const dy = ay - by
  const len = Math.max(1, Math.hypot(dx, dy))

  // normal vector (perpendicular)
  const nx = -dy / len
  const ny = dx / len

  // widths: root wider, tip narrower (你可以调)
  const baseW = 16 // 根部宽
  const tipW = 5 // 尾端宽

  // root edge points (on bubble edge)
  const b1x = bx + nx * (baseW / 2)
  const b1y = by + ny * (baseW / 2)
  const b2x = bx - nx * (baseW / 2)
  const b2y = by - ny * (baseW / 2)

  // tip edge points (near anchor)
  const a1x = ax + nx * (tipW / 2)
  const a1y = ay + ny * (tipW / 2)
  const a2x = ax - nx * (tipW / 2)
  const a2y = ay - ny * (tipW / 2)

  // control points for smooth curve (你可以调 bend)
  const bend = 0.55
  const c1x = bx + dx * 0.25
  const c1y = by + dy * bend
  const c2x = bx + dx * 0.7
  const c2y = by + dy * 0.92

  // closed shape: b1 -> (curve) -> a1 -> line -> a2 -> (curve back) -> b2 -> close
  const tailFillPath = [
    `M ${b1x} ${b1y}`,
    `C ${c1x} ${c1y}, ${c2x} ${c2y}, ${a1x} ${a1y}`,
    `L ${a2x} ${a2y}`,
    `C ${c2x} ${c2y}, ${c1x} ${c1y}, ${b2x} ${b2y}`,
    'Z',
  ].join(' ')

  bubbleG
    .append('path')
    .attr('d', tailFillPath)
    .attr('fill', 'rgba(255,255,255,0.92)') // 跟气泡一致
    .attr('stroke', '#cfcfcf')
    .attr('stroke-width', 1.2)
    .attr('stroke-linejoin', 'round')

  // === word area inside bubble ===
  const PAD = 1
  const topPad = 26 // leave room for title
  const wcX0 = boxX0 + PAD
  const wcX1 = boxX1 - PAD
  const wcY0 = boxY0 + topPad
  const wcY1 = boxY1 - PAD

  const wcW = Math.max(10, wcX1 - wcX0)
  const wcH = Math.max(10, wcY1 - wcY0)

  // clip word area to bubble inner rect
  const clipId = `wc-bubble-clip-${hashTopicId(activeTopicKey.value)}-${ctx.wordcloudTurn}`
  ctx.defs.select(`#${clipId}`).remove()
  ctx.defs
    .append('clipPath')
    .attr('id', clipId)
    .attr('clipPathUnits', 'userSpaceOnUse')
    .append('rect')
    .attr('x', wcX0)
    .attr('y', wcY0)
    .attr('width', wcW)
    .attr('height', wcH)
    .attr('rx', 10)
    .attr('ry', 10)

  const wordsG = wcLayer.append('g').attr('class', 'words').attr('clip-path', `url(#${clipId})`)
  wordsG.style('pointer-events', 'none')

  // === choose words ===
  const MAX_WC = 18
  const words = wc
    .slice()
    .filter((d) => d.word)
    .sort((a, b) => (Number(b.weight) || 0) - (Number(a.weight) || 0))
    .slice(0, MAX_WC)

  // weight scales
  const wArr = words.map((d) => (Number.isFinite(d.weight) ? Number(d.weight) : 0.5))
  let wMin = d3.min(wArr) ?? 0
  let wMax = d3.max(wArr) ?? 1
  if (wMax - wMin < 1e-6) {
    wMin = Math.max(0, wMin - 0.5)
    wMax = Math.min(1, wMax + 0.5)
  }

  // more "wordle-ish" ranges
  const sizeScale = d3.scalePow().exponent(0.8).domain([wMin, wMax]).range([10, 22]).clamp(true)
  const alphaScale = d3.scaleLinear().domain([wMin, wMax]).range([0.45, 1.0]).clamp(true)

  // collision boxes
  type Box = { x0: number; x1: number; y0: number; y1: number }
  const placed: Box[] = []

  // center for spiral search: slightly toward arrow side
  const baseCx = wcX0 + wcW / 2
  const baseCy = wcY0 + wcH / 2
  const cx0 = side === 'L' ? baseCx + wcW * 0.06 : baseCx - wcW * 0.06
  const cy0 = baseCy

  const aspectY = Math.max(1.1, (wcH / wcW) * 2.6)
  const MAX_TRIES = 260
  const PAD2 = 3

  const jitterX = (v: number) => v + (rnd() - 0.5) * 8
  const jitterY = (v: number) => v + (rnd() - 0.5) * 12

  for (const it of words) {
    const w = it.word
    const weight = Number.isFinite(it.weight) ? Number(it.weight) : 0.5
    const fs = sizeScale(weight)

    // create text first to measure
    const t = wordsG
      .append('text')
      .attr('x', 0)
      .attr('y', 0)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('fill', '#222')
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
    const th = fs * 1.08

    // stable rotation (few angles)
    const rPick = rnd()
    const rot = rPick < 0.18 ? -24 : rPick < 0.36 ? 24 : 0

    let ok: { x: number; y: number; box: Box } | null = null

    // spiral search
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

      if (b.x0 < wcX0 || b.x1 > wcX1 || b.y0 < wcY0 || b.y1 > wcY1) continue
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

/**
 * ======================================================================
 * 15) drawUI 外提：Zoom（缩放时刷新 wordcloud）
 * ======================================================================
 */
function setupZoom(ctx: DrawCtx) {
  let viewT: d3.ZoomTransform = d3.zoomIdentity

  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([1, 6])
    .on('zoom', (event) => {
      const t = event.transform
      ctx.zoomK = t.k

      // 缩放锚点：条带中心 +（如果点过词云则以该 turn 为锚点）
      const anchorX = ctx.stripCenter
      const anchorY = ctx.wordcloudTurn ? ctx.yScaleTime(ctx.wordcloudTurn) : ctx.innerHeight / 2

      const srcType = event.sourceEvent?.type

      // wheel：围绕锚点缩放
      if (srcType === 'wheel') {
        const x = viewT.x + (viewT.k - t.k) * anchorX
        const y = viewT.y + (viewT.k - t.k) * anchorY
        viewT = d3.zoomIdentity.translate(x, y).scale(t.k)
      } else {
        // drag/pinch：保持平移
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k ?? t.k)
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k)
      }

      // 应用变换
      ctx.contentG.attr('transform', `translate(${viewT.x},${viewT.y}) scale(${viewT.k})`)

      // 重新绘制词云
      tryRenderWordcloudInBandbubble(ctx)
    })

  ctx.svg.call(zoom)
}

/**
 * ======================================================================
 * 16) drawUI 外提：图例（topic legend + role legend）
 * ======================================================================
 */
function drawLegends(ctx: DrawCtx) {
  const legendWidth = 150
  const legendItemHeight = 18
  const legendPadding = 10

  const topicLegendHeight = legendPadding * 2 + (1 + ctx.topics.length) * legendItemHeight
  const roleLegendWidth = 130
  const roleLegendRows = 2
  const roleLegendHeight = legendPadding * 2 + (1 + roleLegendRows) * legendItemHeight

  const SVG_W = ctx.width
  const LEGEND_MARGIN_RIGHT = 10
  const LEGEND_GAP_Y = 12

  const topicLegendX = SVG_W - ctx.margin.left - legendWidth - LEGEND_MARGIN_RIGHT
  const topicLegendY = 0
  const roleLegendX = topicLegendX
  const roleLegendY = topicLegendY + topicLegendHeight + LEGEND_GAP_Y

  // ----------------
  // topic legend
  // ----------------
  const topicLegendG = ctx.g
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
    .data(ctx.topics)
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

      activeTopics.value = new Set([topic])
      activeTopicKey.value = topic
      highlightTopicBands(activeTopics.value)

      ctx.updateSelectedTopic()
      ctx.syncSlotClouds()
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

  // ----------------
  // role legend
  // ----------------
  const roleLegendG = ctx.g
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
    .data(ctx.speakers)
    .enter()
    .append('g')
    .attr('class', 'speaker-legend-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 8 + i * legendItemHeight})`,
    )
    .style('cursor', 'pointer')
    .on('click', (event, speaker) => {
      event.stopPropagation()

      // ✅ toggle speaker
      const next = activeSpeakerKey.value === speaker ? null : speaker
      activeSpeakerKey.value = next
      ctx.activeSpeakerKey = next

      if (!next) {
        // 取消 speaker 筛选：恢复 topic band/lines，activeTopics 不强制改（你也可清空）
        applySpeakerFilter(ctx)
        // 这里你可以选择：恢复为“当前 activeTopics”，或清空
        // activeTopics.value = new Set()
        // activeTopicKey.value = null
        // highlightTopicBands(null)
        ctx.syncSlotClouds()
        return
      }

      // ✅ speaker -> topics：只显示该 speaker 涉及的 topics
      const keepTopics = ctx.speakerTopics.get(next) ?? new Set<string>()
      activeTopics.value = new Set(keepTopics)
      activeTopicKey.value = keepTopics.size ? Array.from(keepTopics)[0] : null

      // 只显示这些 topic 的 bands（其余隐藏）+ 只显示该 speaker 的线
      applySpeakerFilter(ctx)

      // 同步 slot 云（showSlotCloudInto 内也会过滤为该 speaker）
      ctx.updateSelectedTopic()
      ctx.syncSlotClouds()
    })

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

/**
 * ======================================================================
 * 17) drawUI（主流程：只负责“串流程”）
 * ======================================================================
 */
function drawUI(
  dataArr: Conversation[],
  scoreMap: Map<number, number>,
  STRIP_WIDTH_FIXED: number,
  NUM_WIDTH_BLOCKS: number,
) {
  // 0) 容器检查 & 清空
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()

  // 1) 抽点 & topics（同时写入 topicColorMap）
  const { points, topics } = extractPointsAndTopics(dataArr, scoreMap, topicColorMap)
  const allPoints = points

  const topicsGreedy = topics // ✅ 优化方案：第一行顺序永远不变

  // ❌ baseline：故意给一个很坏的顺序（但可复现）
  const badSeed = BAD_ORDER_SEED.value ^ hash32(props.datasetKey)
  const topicsBaselineBad = makeBadTopicOrder(topics, badSeed)

  // 2) 分配 speaker 颜色 + speakers 列表
  const speakers = assignSpeakerColors(points, speakerColorMap, SPEAKER_PALETTE)

  // 3) 计算 turn 轴 xs
  const { globalMinTurn, globalMaxTurn, xs } = computeXs(points)

  // 4) KDE：topic -> density curve
  const { topicGroup } = computeTopicKDE(points, topics, xs)

  // 5) 画布 / 坐标系参数
  const width = 1000
  const height = 900
  const margin = { top: 20, right: 20, bottom: 30, left: 100 }
  const innerWidth = width - margin.left - margin.right
  const innerHeight = height - margin.top - margin.bottom

  // 6) 创建 svg 与图层
  const { svg, g, contentG, bandLayer, overlayLayer, defs } = createScene(
    UIcontainer.value,
    width,
    height,
    margin,
  )

  // 7) yScale：turnId -> 像素
  const yScaleTime = d3
    .scaleLinear()
    .domain([globalMinTurn, globalMaxTurn])
    .range([10, innerHeight])

  // 8) 画 y 轴
  drawYAxis(g, yScaleTime, innerHeight)

  // 9) 条带中心与固定宽度（用于 rowProfile）
  const stripCenter = innerWidth / 2
  const stripWidthFixed = STRIP_WIDTH_FIXED
  const stripLeftFixed = stripCenter - stripWidthFixed / 2

  // 10) 每行总宽度 rowProfile（score -> rowWidth）
  const rowProfile = buildRowProfile({
    xs,
    turnScoreMap: scoreMap,
    numBlocks: NUM_WIDTH_BLOCKS,
    stripWidthFixed,
    stripCenter,
    minF: 0.2,
    maxF: 1.0,
    gamma: 1.5,
    useSmooth: true,
  })

  // 11) topic 在每行的宽度（KDE -> width）
  const widthByTopicById = computeWidthByTopicById({
    topics,
    xs,
    rowProfile,
    topicGroup,
    alpha: 2,
  })

  // 14) speaker 全局列比例（固定列）
  const speakerFracGlobal = new Map<string, number>()
  buildGlobalSpeakerFrac(speakers, 0.1, speakerFracGlobal)

  // ===============================
  // Baseline（不开优化）：固定顺序 topics
  // ===============================
  const baselineTopicBands = buildTopicBandsFixedOrder({
    topics: topicsBaselineBad,
    xs,
    rowProfile,
    widthByTopicById,
    minWidth: 1,
  })
  const baselineTopicBandById = buildTopicBandById(baselineTopicBands)

  // baseline：用 band + speakerFrac 去给每个点算 x
  const baselineFixedXInTopicRow = makeFixedXInTopicRow({
    topicBandById: baselineTopicBandById,
    speakerFracGlobal,
    stripCenter,
    slotPadX: 30, // 你 baseline 也可以用同一个 pad，方便对比
  })

  const baselineSlotXMap: SlotXMap = new Map()
  for (const p of allPoints) {
    baselineSlotXMap.set(pointKey(p), baselineFixedXInTopicRow(p.topic, p))
  }

  // ===============================
  // Greedy（开优化）：协同优化条带顺序 + 点位置
  // ===============================
  const { topicBands: greedyRawTopicBands, slotXMap: greedySlotXMap } = solveBandsAndSlotsRowWise({
    xs,
    topics: topicsGreedy, // 第一行 base 顺序
    allPoints,
    rowProfile,
    stripCenter,
    widthByTopicById,
    speakerFracGlobal,
    slotPadX: 50,
    minWidth: 1,
    beta: 1,
    gamma: 50,
  })

  // prune 一下（可选，但建议保留你之前的）
  const greedyTopicBands = pruneTopicBands(greedyRawTopicBands)
  const greedyTopicBandById = buildTopicBandById(greedyTopicBands)

  // ===============================
  // ✅ 最终选择：只在这里切换
  // ===============================
  const topicBands = ENABLE_GREEDY_LAYOUT.value ? greedyTopicBands : baselineTopicBands
  const topicBandById = ENABLE_GREEDY_LAYOUT.value ? greedyTopicBandById : baselineTopicBandById
  const slotXMap = ENABLE_GREEDY_LAYOUT.value ? greedySlotXMap : baselineSlotXMap

  // 15) 固定 x：seg 左右边界 + speakerFrac

  // 16) outline path：clipPath 兜底
  const outlinePathD: string | null = computeOutlinePath({ rowProfile, yScaleTime })

  // 17) ctx：把“绘制 session”需要用的东西都集中起来
  const ctx: DrawCtx = {
    svg,
    g,
    contentG,
    bandLayer,
    overlayLayer,
    defs,

    width,
    height,
    margin,
    innerWidth,
    innerHeight,
    stripCenter,
    stripWidthFixed,
    stripLeftFixed,

    dataArr,
    allPoints,
    topics,
    speakers,
    topicGroup,
    xs,
    globalMinTurn,
    globalMaxTurn,

    yScaleTime,
    rowProfile,
    topicBands,
    topicBandById,
    slotXMap,

    outlinePathD,
    topicBandPathMap: new Map<string, string>(),

    selectedTopics: new Set<string>(),
    wordcloudTurn: null,
    wordcloudAnchor: null,
    zoomK: 1,

    activeSpeakerKey: null,
    speakerTopics: new Map(),

    updateSelectedTopic: () => {},
    syncSlotClouds: () => {},
    resetAll: () => {},
  }

  // ✅ 建 speaker -> topics 索引（给角色图例点击用）
  ctx.speakerTopics = buildSpeakerTopicsIndex(allPoints)
  ctx.activeSpeakerKey = null

  // 18) 选中 topic：更新 AddTalk 上下文 + 高亮
  ctx.updateSelectedTopic = () => {
    // 以 activeTopics 为准，合并多个 topic 的 msgs（用于 AddTalk）
    const selected = activeTopics.value
    if (!selected || selected.size === 0) {
      selectedTopicMessages.value = []
      highlightTopicBands(null)
      return
    }

    const msgs = ctx.dataArr
      .filter((c) => selected.has(c.topic ?? 'Unknown Topic'))
      .flatMap((c) =>
        (c.slots || []).map((s) => ({
          id: s.id,
          role: s.source,
          content: s.sentence,
        })),
      )

    selectedTopicMessages.value = msgs

    // 高亮也以 activeTopics 为准
    highlightTopicBands(selected)
  }

  // 19) reset：清 activeTopics / 高亮 / slot 云 / 词云
  ctx.resetAll = () => {
    clearSpeakerFilter(ctx)

    activeTopics.value = new Set()
    activeTopicKey.value = null
    highlightTopicBands(null)

    const root = ctx.overlayLayer.select<SVGGElement>('.slot-global-cloud-root')
    if (!root.empty()) root.selectAll('*').remove()

    const wcBubble = ctx.contentG.select<SVGGElement>('.slot-wordcloud-bubble')
    if (!wcBubble.empty()) wcBubble.selectAll('*').remove()

    const wcInband = ctx.contentG.select<SVGGElement>('.slot-wordcloud-inband')
    if (!wcInband.empty()) wcInband.selectAll('*').remove()

    ctx.wordcloudTurn = null
    ctx.wordcloudAnchor = null
  }

  // 20) syncSlotClouds：渲染多个 topic 云
  ctx.syncSlotClouds = () => syncSlotClouds(ctx)

  // 21) svg click：只绑定一次 reset（避免 showSlotCloudInto 重复绑）
  ctx.svg.on('click', () => ctx.resetAll())

  // if (outlinePathD) {
  //   ctx.overlayLayer
  //     .append('path')
  //     .attr('class', 'strip-outline')
  //     .attr('d', outlinePathD)
  //     .attr('fill', 'none')
  //     .attr('stroke', '#111')
  //     .attr('stroke-width', 1.2)
  //     .attr('stroke-opacity', 0.35)
  //     .lower() // 放到底层，避免挡住交互
  // }

  // 22) 画 bands（绑定点击逻辑）
  renderTopicBands(ctx)

  // 23) zoom（缩放刷新词云）
  setupZoom(ctx)

  // 24) 画全局 speaker 连线
  drawGlobalSpeakerLines(ctx)

  // 25) 图例
  drawLegends(ctx)
}

// -----------------------------
// 9) 监听：外部数据变化（保留你的 debug）
// -----------------------------
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

// -----------------------------
// 10) 监听数据集切换：加载并绘制
// -----------------------------
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

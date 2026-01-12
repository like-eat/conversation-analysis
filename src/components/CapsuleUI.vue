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

type PointWithLayout = Point & {
  _x: number
  _y: number
  _ty: number
}

const datasetName = computed(() => {
  return props.datasetKey === 'meeting' ? '多人会议' : '心理疾病'
})

//  2) 全局 Store / 响应式状态
const FileStore = useFileStore()

const UIcontainer = ref<HTMLElement | null>(null)
const activeTopicKey = ref<string | null>(null)

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

// KDE 带宽（按你之前 html 的设置）
const BANDWIDTH = 8

// 每个发言人一个颜色
const SPEAKER_PALETTE = ['#14B8A6', '#C026D3', '#A3E635', '#FB7185', '#0F172A']

//  4) Props / Emits（切换数据集）
type DatasetKey = 'meeting' | 'xinli'
const props = defineProps<{ datasetKey: DatasetKey }>()
const emit = defineEmits<{ (e: 'toggle-dataset'): void }>()

const DATASETS: Record<DatasetKey, { convUrl: string; scoreUrl: string }> = {
  meeting: {
    convUrl: '/meeting_result.json',
    scoreUrl: '/meeting_score.json',
  },
  xinli: {
    convUrl: '/xinli_result.json',
    scoreUrl: '/xinli_score.json',
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

// 高亮选中 topic 带（其余 topic 降透明度）
const highlightTopicBands = (activeTopic: string | null) => {
  const bands = d3.selectAll<SVGPathElement, Segment[]>('path.topic-band')

  bands
    .interrupt()
    .transition()
    .duration(400)
    .ease(d3.easeCubicInOut)
    .attr('fill-opacity', function () {
      const t = d3.select(this).attr('data-topic')
      if (!activeTopic) return 0.85
      return t === activeTopic ? 1.0 : 0.2
    })
    .attr('transform', function () {
      const t = d3.select(this).attr('data-topic')
      if (!activeTopic || t !== activeTopic) return 'translate(0,0) scale(1,1)'
      return 'translate(0,0) scale(1,1)'
    })
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

  // 三、保留高亮效果
  if (activeTopicKey.value) {
    highlightTopicBands(activeTopicKey.value)
  }
}

// 清除 slot 连线（只删 path，不删文本/圆点）
const DeleteLine = () => {
  d3.select('.slot-global-cloud').selectAll('.speaker-slot-line').remove()
}

//  6) 加载数据并绘制
async function loadAndDraw(key: DatasetKey) {
  const { convUrl, scoreUrl } = DATASETS[key]

  const convResp = await fetch(convUrl)
  const convJson: Conversation[] = await convResp.json()

  const scoreResp = await fetch(scoreUrl)
  const scoreJson: Array<{ id: number; info_score: number }> = await scoreResp.json()

  // 写入分数映射
  turnScoreMap.clear()
  scoreJson.forEach((item) => turnScoreMap.set(item.id, item.info_score))

  // （建议）切换数据时清掉旧的颜色/高亮状态，避免残留
  activeTopicKey.value = null
  selectedTopicMessages.value = []
  Object.keys(topicColorMap).forEach((k) => delete topicColorMap[k])
  Object.keys(speakerColorMap).forEach((k) => delete speakerColorMap[k])

  data.value = convJson
  drawUI(convJson, turnScoreMap)
}

//  7) 绘制主 UI（KDE 条带 + 图例 + slot 云 + lens）
function drawUI(dataArr: Conversation[], turnScoreMap: Map<number, number>) {
  if (!UIcontainer.value) return

  // 清空画布
  d3.select(UIcontainer.value).selectAll('*').remove()

  let zoomK = 1
  const WORDCLOUD_ZOOM_THRESHOLD = 1.5

  // ===== 额外：slot lens（局部放大镜）=====
  let wordcloudTurn: number | null = null

  // [新增] 保存总条带外轮廓 path（用于 clipPath 裁剪 slot 云）
  let outlinePathDataForClip: string | null = null

  // ===== 1) 抽点：Conversation[] -> points[] =====
  const points: Point[] = []
  const topicsSet = new Set<string>()

  dataArr.forEach((conv) => {
    const topic = conv.topic ?? 'Unknown Topic'
    const slots = conv.slots ?? []
    topicsSet.add(topic)
    topicColorMap[topic] = conv.color

    slots.forEach((s) => {
      if (typeof s.id !== 'number') return

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

  const nested = d3.group(points, (d) => d.topic)
  nested.forEach((arr, topic) => {
    const topicColor = arr[0]?.topicColor || '#1f77b4'
    const ids = Array.from(new Set(arr.map((d) => d.id))).sort((a, b) => a - b)
    const values = computeKDE1D(ids, xs, BANDWIDTH)
    topicGroup.set(topic, { color: topicColor, values })
  })

  // ===== 4) 布局参数 =====
  const width = 1000
  const height = 800
  const MARGIN = { top: 20, right: 20, bottom: 40, left: 100 }
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
  const STRIP_WIDTH = Math.min(500, innerWidth - 100)
  const STRIP_LEFT = 150
  const STRIP_CENTER = STRIP_LEFT + STRIP_WIDTH / 2

  // ===== 5) 生成“每一行总条带宽度” profile（按 block 平滑）=====
  const totalSteps = xs.length
  const NUM_WIDTH_BLOCKS = Math.min(5, totalSteps)
  const BLOCK_SIZE = Math.ceil(totalSteps / NUM_WIDTH_BLOCKS)

  const rowProfile = new Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>()

  // 取分数范围 -> 映射到宽度系数
  const scores = points.map((p) => p.info_score ?? 0.5)
  const scoreMin = d3.min(scores) ?? 0.2
  const scoreMax = d3.max(scores) ?? 1.0
  const widthScale = d3.scaleLinear().domain([scoreMin, scoreMax]).range([0.3, 1])

  const getTurnWidthFactor = (id: number) => {
    const s = turnScoreMap.get(id)
    const score = s ?? (scoreMin + scoreMax) / 2
    return widthScale(score)
  }

  // 每块的平均 factor
  const blockAvg: number[] = new Array(NUM_WIDTH_BLOCKS).fill(NaN)

  for (let bi = 0; bi < NUM_WIDTH_BLOCKS; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    let sumFactor = 0
    let cnt = 0
    for (const id of blockIds) {
      const f = getTurnWidthFactor(id)
      if (Number.isFinite(f)) {
        sumFactor += f
        cnt++
      }
    }
    blockAvg[bi] = cnt ? sumFactor / cnt : 1
  }

  // 块内插值填进 rowProfile
  for (let bi = 0; bi < NUM_WIDTH_BLOCKS; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    const cur = Number.isFinite(blockAvg[bi]) ? blockAvg[bi] : 1
    const nextIdx = Math.min(bi + 1, NUM_WIDTH_BLOCKS - 1)
    const next = Number.isFinite(blockAvg[nextIdx]) ? blockAvg[nextIdx] : cur

    const L = blockIds.length
    for (let k = 0; k < L; k++) {
      const id = blockIds[k]
      const t = L <= 1 ? 0 : k / (L - 1)
      const tt = t * t * (3 - 2 * t) // smoothstep

      const factor = cur + (next - cur) * tt

      const rowWidth = STRIP_WIDTH * factor
      const halfWidth = rowWidth / 2
      const stripLeft = STRIP_CENTER - halfWidth
      const stripRight = STRIP_CENTER + halfWidth

      rowProfile.set(id, { rowWidth, stripLeft, stripRight })
    }
  }

  // ===== 6) 每个 topic 的条带几何（每行分配宽度）=====
  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  xs.forEach((id, idx) => {
    const rp = rowProfile.get(id)
    if (!rp) return

    const localWidth = rp.rowWidth
    const stripLeft = rp.stripLeft
    const stripRight = rp.stripRight

    const densities = topics.map((t) => topicGroup.get(t)!.values[idx]?.value ?? 0)
    const sumDensity = d3.sum(densities)
    if (!sumDensity || sumDensity <= 0) return

    const ALPHA = 2
    let weighted = densities.map((v) => (v > 0 ? Math.pow(v, ALPHA) : 0))
    let sumWeighted = d3.sum(weighted)

    if (!sumWeighted || sumWeighted <= 0) {
      weighted = topics.map(() => 1)
      sumWeighted = topics.length
    }

    let cursor = stripLeft
    topics.forEach((topic, ti) => {
      const wv = weighted[ti]
      if (wv <= 0) return

      const wTopic = (wv / sumWeighted) * localWidth
      const left = cursor
      const right = cursor + wTopic

      topicBands.get(topic)!.push({ id, left, right })
      cursor = right
    })

    // 防止累计误差：最后一个贴边
    const lastTopic = topics[topics.length - 1]
    const arr = topicBands.get(lastTopic)!
    arr[arr.length - 1].right = stripRight
  })

  // topic -> (turnId -> {left,right})
  const topicBandById = new Map<string, Map<number, Segment>>()
  topicBands.forEach((segs, topic) => {
    const m = new Map<number, Segment>()
    segs.forEach((s) => m.set(s.id, s))
    topicBandById.set(topic, m)
  })

  // topic -> (speaker -> frac in (0,1))  固定列比例（不贴边）
  const speakerFracByTopic = new Map<string, Map<string, number>>()
  topics.forEach((topic) => {
    const spList = Array.from(
      new Set(
        allPoints
          .filter((p) => p.topic === topic)
          .map((p) => (p.source || '').trim())
          .filter(Boolean),
      ),
    ).sort()

    const n = spList.length
    const m = new Map<string, number>()
    spList.forEach((sp, i) => {
      const EDGE_PAD = 0.08 // 0~0.2 建议
      let frac = 0.5
      if (n === 1) frac = 0.5
      else frac = EDGE_PAD + (1 - 2 * EDGE_PAD) * (i / (n - 1))
      m.set(sp, frac)
    })
    speakerFracByTopic.set(topic, m)
  })

  // [NEW] slot 的 x：根据 “该topic该行band左右边界” + “speaker固定列比例” 计算
  const SLOT_PAD_X = 12
  function fixedXInTopicRow(topic: string, p: Point): number {
    const seg = topicBandById.get(topic)?.get(p.id)
    if (!seg) return STRIP_CENTER

    const sp = (p.source || '').trim()
    const frac = speakerFracByTopic.get(topic)?.get(sp) ?? 0.5

    const innerW = Math.max(6, seg.right - seg.left - 2 * SLOT_PAD_X)
    return seg.left + SLOT_PAD_X + frac * innerW
  }

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
    selectedTopicMessages.value = msgs
    highlightTopicBands(topic)
  }

  let wordcloudAnchor: { id: number; x: number; y: number } | null = null

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
    const boxH = 120
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

    function intersects(b: Box): boolean {
      for (const p of placed) {
        const separated = b.x1 < p.x0 || b.x0 > p.x1 || b.y1 < p.y0 || b.y0 > p.y1
        if (!separated) return true
      }
      return false
    }

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
        .attr('fill', '#111')
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
        if (intersects(b)) continue

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
        // 但缩放比例仍然用 t.k（拖拽时 t.k 通常不变）
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k ?? t.k)
        // 更稳一点：直接继承当前 k
        viewT = d3.zoomIdentity.translate(t.x, t.y).scale(viewT.k)
      }

      contentG.attr('transform', `translate(${viewT.x},${viewT.y}) scale(${viewT.k})`)

      tryRenderWordcloudInBand()
    })

  svg.call(zoom)

  // ===== 7) 图例布局参数 =====
  const legendWidth = 170
  const legendItemHeight = 18
  const legendPadding = 10

  const topicLegendHeight = legendPadding * 2 + (1 + topics.length) * legendItemHeight

  const roleLegendWidth = 130
  const roleLegendRows = 2
  const roleLegendHeight = legendPadding * 2 + (1 + roleLegendRows) * legendItemHeight

  const topicLegendX = STRIP_LEFT + STRIP_WIDTH + 20
  const topicLegendY = 0

  const roleLegendX = topicLegendX
  const roleLegendY = topicLegendY + topicLegendHeight + 12

  // ===== 8) 全局 slot 云（点击 topic 后显示）=====
  function showSlotCloud(topic: string) {
    // 1) 取出该 topic 下的所有 slot，按时间排序
    const allSlots = allPoints.filter((p) => p.topic === topic).sort((a, b) => a.id - b.id)

    if (!allSlots.length) {
      const emptyLayer = contentG.select<SVGGElement>('.slot-global-cloud')
      if (!emptyLayer.empty()) emptyLayer.style('display', 'none')
      return
    }

    // [ADD] 只展示前 N 条 slot
    const maxSlots = 40
    const lines = allSlots.slice(0, maxSlots)

    // ----------------------------
    // [MOVE UP] resolveY 必须在使用前定义（否则会报错）
    // ----------------------------
    function resolveY(points: PointWithLayout[], yMin: number, yMax: number, minGap: number) {
      const ps = points.slice().sort((a, b) => a._ty - b._ty)

      // 向下推开
      let cur = yMin
      for (const d of ps) {
        cur = Math.max(d._ty, cur)
        d._y = cur
        cur += minGap
      }

      // 底部溢出：整体往上挪
      const overflow = ps[ps.length - 1]._y - yMax
      if (overflow > 0) {
        for (const d of ps) d._y -= overflow
      }

      // 再从下往上修一遍，防止挤回去重叠
      for (let i = ps.length - 2; i >= 0; i--) {
        const maxAllowed = ps[i + 1]._y - minGap
        ps[i]._y = Math.min(ps[i]._y, maxAllowed)
      }

      // 顶部兜底
      const topOverflow = yMin - ps[0]._y
      if (topOverflow > 0) {
        for (const d of ps) d._y += topOverflow
      }
    }

    // 0) 先把 Point 转成 PointWithLayout
    const linesWL: PointWithLayout[] = lines.map((d) => {
      const ty = yScaleTime(d.id)
      return { ...d, _ty: ty, _y: ty, _x: 0 }
    })

    // ===== [NEW] 写死 x：每个点都落在“该topic该行band范围内” =====
    linesWL.forEach((d) => {
      d._x = fixedXInTopicRow(topic, d)
    })

    // 3) 每列 y 避让（避免重叠）
    const bySpeakerCol = d3.group(linesWL, (d) => (d.source || '').trim())
    bySpeakerCol.forEach((arr) => {
      resolveY(arr, 0, innerHeight, 10)
    })

    // 4) 初始化 / 清空图层
    let cloudLayer = overlayLayer.select<SVGGElement>('.slot-global-cloud')
    if (cloudLayer.empty()) cloudLayer = overlayLayer.append('g').attr('class', 'slot-global-cloud')

    // 再保险：每次显示都 raise 到最顶
    cloudLayer.raise()

    cloudLayer
      .interrupt()
      .style('display', null)
      .style('opacity', 0)
      .attr('transform', 'translate(0, 12) scale(0.96)')

    cloudLayer.selectAll('*').remove()

    const lineLayer = cloudLayer.append('g').attr('class', 'slot-line-layer')
    const labelLayer = cloudLayer.append('g').attr('class', 'slot-label-layer')

    const defs = g.select('defs').empty() ? g.append('defs') : g.select('defs')

    // [CHANGE] clip 用当前 topic 的 band，而不是总轮廓
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

    // 字体/透明度范围（按 i 衰减）
    const minFont = 10
    const maxFont = 18
    const minOpacity = 0.35
    const maxOpacity = 1.0

    // 5) 画 slot 文本组（圆点 + 文本）
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

    // ===== 同一发言者连线（按 source 分组）=====
    const lineGen = d3
      .line<[number, number]>()
      .x((p) => p[0])
      .y((p) => p[1])
      .curve(d3.curveMonotoneY)

    const bySpeaker = d3.group(linesWL, (d) => d.source)

    bySpeaker.forEach((slotsOfSpeaker, speakerName) => {
      if (!speakerName) return
      if (!slotsOfSpeaker || slotsOfSpeaker.length < 2) return

      const sorted = slotsOfSpeaker.slice().sort((a, b) => a.id - b.id)
      const coords: [number, number][] = sorted.map((d) => [d._x, d._y])

      lineLayer
        .append('path')
        .attr('class', 'speaker-slot-line')
        .attr('d', lineGen(coords)!)
        .attr('fill', 'none')
        .attr('stroke', speakerColorMap[speakerName] || '#999')
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 1)
    })

    // 圆点
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

    // 文本
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

    // 淡入动画
    cloudLayer
      .transition()
      .duration(450)
      .ease(d3.easeCubicOut)
      .style('opacity', 1)
      .attr('transform', 'translate(0, 0) scale(1)')

    function resetAll() {
      activeTopicKey.value = null
      highlightTopicBands(null)

      const lensLayer = g.select<SVGGElement>('.slot-lens-layer')
      if (!lensLayer.empty()) lensLayer.selectAll('*').remove()

      const cloudLayer2 = contentG.select<SVGGElement>('.slot-global-cloud')
      if (!cloudLayer2.empty()) {
        cloudLayer2
          .interrupt()
          .transition()
          .duration(300)
          .ease(d3.easeCubicIn)
          .style('opacity', 0)
          .on('end', () => {
            cloudLayer2.selectAll('*').remove()
            cloudLayer2.style('display', 'none')
          })
      }

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

    bandLayer
      .append('path')
      .attr('class', 'strip-outline')
      .attr('d', outlinePathData!)
      .attr('fill', 'none')
      .attr('stroke', '#e0e0e0')
      .attr('stroke-width', 1.2)
  }

  // ===== 9.5) [NEW] 存每个 topic band 的 path（用于 clip slot 云）=====
  const topicBandPathMap = new Map<string, string>()

  // ===== 10) 画每个 topic band，并绑定点击事件 =====
  topicBands.forEach((segments, topic) => {
    const color = topicGroup.get(topic)!.color

    const area = d3
      .area<Segment>()
      .y((d) => yScaleTime(d.id))
      .x0((d) => d.left)
      .x1((d) => d.right)
      .curve(d3.curveBasis)

    // [NEW] 预先算出这个 topic 的 band path，供 showSlotCloud 里做 clipPath
    const bandPathD = area(segments) ?? ''
    topicBandPathMap.set(topic, bandPathD)

    bandLayer
      .append('path')
      .datum(segments)
      .attr('class', 'topic-band')
      .attr('d', bandPathD)
      .attr('fill', color)
      .attr('fill-opacity', 0.85)
      .attr('data-topic', topic)
      .style('cursor', 'pointer')
      .on('click', (event) => {
        event.stopPropagation()
        console.log('点击 topic：', topic)
        updateSelectedTopic(topic)

        const gNode = g.node() as SVGGElement | null
        if (!gNode) return

        const current = activeTopicKey.value
        const next = current === topic ? null : topic
        activeTopicKey.value = next

        if (next) {
          showSlotCloud(topic)
        } else {
          // 1) 隐藏 slot 云
          const cloudLayer = contentG.select<SVGGElement>('.slot-global-cloud')
          if (!cloudLayer.empty()) cloudLayer.style('display', 'none')

          const wcLayer = contentG.select<SVGGElement>('.slot-wordcloud-inband')
          if (!wcLayer.empty()) wcLayer.selectAll('*').remove()
          wordcloudTurn = null

          // 2) lens（保留，但不再用它展示词云）
          const wordcloudLayer = g.select<SVGGElement>('.slot-lens-layer')
          if (!wordcloudLayer.empty()) wordcloudLayer.selectAll('*').remove()
        }
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
    .attr('font-size', 11)
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

//  8) KDE 工具函数（不改名字）
function computeKDE1D(
  samples: number[],
  xs: number[],
  bandwidth: number,
): { x: number; value: number }[] {
  const n = samples.length
  if (n === 0) return xs.map((x) => ({ x, value: 0 }))

  const h = bandwidth
  const invH = 1 / h
  const values = xs.map((x) => ({ x, value: 0 }))

  for (const t of samples) {
    for (const v of values) {
      const u = (v.x - t) * invH
      v.value += Math.exp(-0.5 * u * u)
    }
  }

  const normFactor = 1 / (n * h * Math.sqrt(2 * Math.PI))
  for (const v of values) v.value *= normFactor

  return values
}

//  9) 监听：外部数据变化
// 监听 GPT 返回内容的变化（你原来的保留）
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
  height: 800px;
  margin-top: 10px;
}

.dataset-label {
  width: 1000px;
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 700;
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

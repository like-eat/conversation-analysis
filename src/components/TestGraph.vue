<template>
  <div class="capsule-container">
    <div ref="containerRef" class="capsule-body"></div>
    <div class="dataset-label">{{ datasetName }}</div>

    <!-- 操作按钮（前两个占位） -->
    <button class="bottom-left-btn" @click="DeleteLine">清除线条</button>
    <button class="bottom-mid-btn" @click="AddTalk">新开分支</button>
    <button class="bottom-right-btn" @click="emit('toggle-dataset')">切换数据</button>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { computed, onMounted, ref, watch } from 'vue'
import { computeKDE1D } from '@/utils/Methods'
import type { Conversation } from '@/types/index'

const containerRef = ref<HTMLDivElement | null>(null)

const DeleteLine = () => {
  // 这里做“清除线条”的真实逻辑：把线层清空即可
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('.speaker-line').remove()
  console.log('DeleteLine: removed speaker lines')
}

const AddTalk = () => {
  console.log('AddTalk (TODO)')
}

// 1) props/emits
type DatasetKey = 'meeting' | 'xinli'
const props = defineProps<{ datasetKey: DatasetKey }>()
const emit = defineEmits<{ (e: 'toggle-dataset'): void }>()

// 2) 数据集配置（conv + score）
const DATASETS: Record<
  DatasetKey,
  { convUrl: string; scoreUrl: string; width: number; blocks: number }
> = {
  meeting: {
    convUrl: '/meeting_result.json',
    scoreUrl: '/meeting_info_with_scores.json',
    width: 800,
    blocks: 20,
  },
  xinli: {
    convUrl: '/xinli_result.json',
    scoreUrl: '/xinli_info_with_scores.json',
    width: 600,
    blocks: 10,
  },
}

// 3) 顶部标签
const datasetName = computed(() => (props.datasetKey === 'meeting' ? '多人会议' : '心理疾病'))
const resultUrl = computed(() => DATASETS[props.datasetKey].convUrl)
const scoreUrl = computed(() => DATASETS[props.datasetKey].scoreUrl)
const BASE_WIDTH = computed(() => DATASETS[props.datasetKey].width)
const NUM_WIDTH_BLOCKS = computed(() => DATASETS[props.datasetKey].blocks)

// ===== 配色：speaker =====
const SPEAKER_PALETTE = ['#14B8A6', '#C026D3', '#A3E635', '#FB7185', '#0F172A']
const speakerColorMap: Record<string, string> = {}

// ===== 交互：topic 多选（高亮用）=====
const activeKeys = new Set<string>() // 选中的 topic keys

function clearContainer() {
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('*').remove()
}

async function draw() {
  if (!containerRef.value) return
  clearContainer()
  activeKeys.clear()

  // ----------------------------
  // 1) 布局参数（rotate 90：交换宽高）
  // ----------------------------
  const margin = { top: 0, right: 30, bottom: 0, left: 10 }

  // plotW/plotH：这是“旋转前”的坐标系
  const plotW = 900 - margin.left - margin.right
  const plotH = 700 - margin.top - margin.bottom

  // svgW/svgH：旋转后视觉上宽高互换
  const svgW = plotH + margin.left + margin.right
  const svgH = plotW + margin.top + margin.bottom

  // 图例
  const legendPadding = 10
  const legendItemH = 18
  const legendBox = 12
  const legendW = 140

  // 主题图例位置（放在右侧）
  const legendX = plotW + margin.left - legendW / 2
  const legendY = margin.top + 10

  // ----------------------------
  // 2) 创建 svg + root g（后面会 rotate）
  // ----------------------------
  const svg = d3
    .select(containerRef.value)
    .append('svg')
    .attr('width', svgW)
    .attr('height', svgH)
    .style('overflow', 'visible')

  const g = svg
    .append('g')
    .attr('class', 'root')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  // layers
  const bandRoot = g.append('g').attr('class', 'band-root')

  // overlay：跟着旋转
  const overlayRoot = g.append('g').attr('class', 'overlay-root')

  // 线层在下
  const lineRoot = overlayRoot.append('g').attr('class', 'speaker-lines-root')

  // 点/文本层在上
  const labelRoot = overlayRoot.append('g').attr('class', 'slot-labels-root')

  // ----------------------------
  // 3) 读取数据（conv + score）
  // ----------------------------
  const convJson: Conversation[] = await (await fetch(resultUrl.value)).json()
  const scoreArr: Array<{
    id: number
    topic_id?: number
    topic_name?: string
    strength?: number
    confidence?: number
    info_score: number
  }> = await (await fetch(scoreUrl.value)).json()

  // 清空旧 speakerColorMap
  Object.keys(speakerColorMap).forEach((k) => delete speakerColorMap[k])

  // speakers（跨 topic）
  const allSpeakers = Array.from(
    new Set(
      convJson
        .flatMap((c: any) => c.slots ?? [])
        .map((s: any) => (s.source ?? 'Unknown').toString().trim())
        .filter((x: string) => x.length > 0),
    ),
  ).sort()

  allSpeakers.forEach((name, idx) => {
    speakerColorMap[name] = SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length]
  })

  // turnScoreMap: id -> info_score
  const turnScoreMap = new Map<number, number>()
  for (const it of scoreArr) {
    const id = Number((it as any)?.id)
    const s = Number((it as any)?.info_score)
    if (Number.isFinite(id) && Number.isFinite(s)) turnScoreMap.set(id, s)
  }

  // ----------------------------
  // 4) topic -> samples（turn ids） + globalMin/globalMax
  // ----------------------------
  const samplesByTopic = new Map<string, number[]>()
  const colorByTopic = new Map<string, string>()

  let globalMin = Number.POSITIVE_INFINITY
  let globalMax = Number.NEGATIVE_INFINITY

  for (const conv of convJson as any[]) {
    const topic = (conv.topic ?? 'Unknown').toString()
    const slots = conv.slots ?? []

    if (!samplesByTopic.has(topic)) samplesByTopic.set(topic, [])
    if (conv.color && !colorByTopic.has(topic)) colorByTopic.set(topic, conv.color)

    for (const s of slots) {
      const id = Number(s.id)
      if (!Number.isFinite(id)) continue
      samplesByTopic.get(topic)!.push(id)
      globalMin = Math.min(globalMin, id)
      globalMax = Math.max(globalMax, id)
    }
  }

  if (!Number.isFinite(globalMin) || !Number.isFinite(globalMax) || globalMin > globalMax) return

  const keys = Array.from(samplesByTopic.keys())
  const xs = d3.range(globalMin, globalMax + 1)

  // ----------------------------
  // 5) 计算 KDE：topic -> [{x,value}]
  // ----------------------------
  const totalSteps = xs.length
  const bandwidth = Math.max(6, Math.round(totalSteps / 50))

  const kdeByTopic = new Map<string, { x: number; value: number }[]>()
  for (const key of keys) {
    const samples = Array.from(new Set(samplesByTopic.get(key)!)).sort((a, b) => a - b)
    const values = computeKDE1D(samples, xs, bandwidth)
    kdeByTopic.set(key, values)
  }

  // ----------------------------
  // 6) 用 info_score 做 block 平滑，得到 rowWeightMap: id -> weight
  // ----------------------------
  const MIN_F = 0.4
  const MAX_F = 1
  const GAMMA = 1.5
  const USE_SMOOTH = true

  function clampScore(score: number) {
    // 这里我保持和你条带图一致：至少 0.2
    // 如果你希望允许更小（更瘦），可以改成 Math.max(0, Math.min(1, score))
    return Math.max(0.2, Math.min(1, score))
  }

  const BLOCK_SIZE = Math.ceil(totalSteps / NUM_WIDTH_BLOCKS.value)

  const blockAvgScore: number[] = new Array(NUM_WIDTH_BLOCKS.value).fill(NaN)
  for (let bi = 0; bi < NUM_WIDTH_BLOCKS.value; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    let sum = 0
    let cnt = 0
    for (const id of blockIds) {
      const s = clampScore(turnScoreMap.get(id) ?? 0.6)
      sum += s
      cnt++
    }
    blockAvgScore[bi] = cnt ? sum / cnt : NaN
  }

  const valid = blockAvgScore.filter(Number.isFinite) as number[]
  const bMin = valid.length ? Math.min(...valid) : 0.2
  const bMax = valid.length ? Math.max(...valid) : 1.0

  function blockScoreToFactor(avgScore: number) {
    if (!(bMax > bMin)) return (MIN_F + MAX_F) / 2
    const s = clampScore(avgScore)
    const t = (s - bMin) / (bMax - bMin)
    const t2 = Math.pow(Math.max(0, Math.min(1, t)), GAMMA)
    return MIN_F + (MAX_F - MIN_F) * t2
  }

  const blockFactor: number[] = blockAvgScore.map((s) =>
    Number.isFinite(s) ? blockScoreToFactor(s) : (MIN_F + MAX_F) / 2,
  )

  const rowWeightMap = new Map<number, number>()
  for (let bi = 0; bi < NUM_WIDTH_BLOCKS.value; bi++) {
    const startIdx = bi * BLOCK_SIZE
    const endIdx = Math.min(startIdx + BLOCK_SIZE, totalSteps)
    if (startIdx >= endIdx) break

    const blockIds = xs.slice(startIdx, endIdx)
    if (!blockIds.length) continue

    const cur = blockFactor[bi]
    const next = blockFactor[Math.min(bi + 1, NUM_WIDTH_BLOCKS.value - 1)]
    const L = blockIds.length

    for (let k = 0; k < L; k++) {
      const id = blockIds[k]
      let factor = cur
      if (USE_SMOOTH) {
        const t = L <= 1 ? 0 : k / (L - 1)
        const tt = t * t * (3 - 2 * t)
        factor = cur + (next - cur) * tt
      }
      rowWeightMap.set(id, BASE_WIDTH.value * factor)
    }
  }

  // ----------------------------
  // 7) 拼 streamgraph wide data（关键：每列乘 rowWeight）
  // ----------------------------
  const data = xs.map((id, i) => {
    const row: any = { x: id }
    const w = rowWeightMap.get(id) ?? BASE_WIDTH.value * 0.6
    for (const key of keys) {
      row[key] = (kdeByTopic.get(key)![i]?.value ?? 0) * w
    }
    return row
  })

  // topic color
  const fallback = d3
    .scaleOrdinal<string, string>()
    .domain(keys)
    .range(d3.schemeDark2 as any)
  const topicColor = (k: string) => colorByTopic.get(k) ?? fallback(k)

  // ----------------------------
  // 8) scales + stack + area
  // ----------------------------
  const x = d3
    .scaleLinear()
    .domain(d3.extent(data, (d: any) => d.x) as [number, number])
    .range([0, plotW])

  const stackedData = d3
    .stack<any, string>()
    .keys(keys)
    .order(d3.stackOrderInsideOut)
    .offset(d3.stackOffsetWiggle)(data)

  const yMin = d3.min(stackedData, (layer) => d3.min(layer, (d) => d[0])) ?? 0
  const yMax = d3.max(stackedData, (layer) => d3.max(layer, (d) => d[1])) ?? 1
  const y = d3.scaleLinear().domain([yMin, yMax]).range([plotH, 0])

  const area = d3
    .area<any>()
    .x((d: any) => x(d.data.x))
    .y0((d: any) => y(d[0]))
    .y1((d: any) => y(d[1]))
    .curve(d3.curveBasis)

  // ----------------------------
  // 9) 预计算 bandByTopic：topic -> (id -> {top,bot})
  // ----------------------------
  type Band = { top: number; bot: number }
  const bandByTopic = new Map<string, Map<number, Band>>()

  for (const layer of stackedData as any[]) {
    const topic = layer.key as string
    const m = new Map<number, Band>()
    for (const pt of layer as any[]) {
      const id = Number(pt.data.x)
      const y0 = y(pt[0])
      const y1 = y(pt[1])
      m.set(id, { top: Math.min(y0, y1), bot: Math.max(y0, y1) })
    }
    bandByTopic.set(topic, m)
  }

  // ----------------------------
  // 10) 画轴（保持你之前的）
  // ----------------------------
  g.append('g')
    .attr('transform', `translate(0,${plotH * 0.8})`)
    .call(
      d3
        .axisBottom(x)
        .tickSize(-plotH * 0.7)
        .ticks(10)
        .tickFormat(d3.format('d')),
    )
    .select('.domain')
    .remove()

  g.selectAll('.tick line').attr('stroke', '#b8b8b8')

  // ----------------------------
  // 11) 画 stream layers + 多选高亮
  // ----------------------------
  function applySelection() {
    const hasSelection = activeKeys.size > 0
    bandRoot
      .selectAll<SVGPathElement, any>('path.myArea')
      .style('opacity', (d: any) => (!hasSelection ? 1 : activeKeys.has(d.key) ? 1 : 0.2))
      .style('stroke', (d: any) =>
        !hasSelection ? 'none' : activeKeys.has(d.key) ? '#111' : 'none',
      )
      .style('stroke-width', (d: any) => (!hasSelection ? 0 : activeKeys.has(d.key) ? 1.2 : 0))
  }

  const onLayerClick = (event: MouseEvent, d: any) => {
    event.stopPropagation()
    const key = d.key as string

    if (event.shiftKey) {
      if (activeKeys.has(key)) activeKeys.delete(key)
      else activeKeys.add(key)
    } else {
      if (activeKeys.size === 1 && activeKeys.has(key)) activeKeys.clear()
      else {
        activeKeys.clear()
        activeKeys.add(key)
      }
    }
    updateTopicLegendStyle()
    applySelection()
    drawSlotLabels()
  }

  bandRoot
    .selectAll('mylayers')
    .data(stackedData)
    .enter()
    .append('path')
    .attr('class', 'myArea')
    .style('fill', (d: any) => topicColor(d.key))
    .attr('d', area as any)
    .on('click', onLayerClick)

  // 点击空白：清 selection（线仍显示）
  svg.on('click', () => {
    activeKeys.clear()
    applySelection()
    updateTopicLegendStyle()
    drawSlotLabels()
  })

  // ----------------------------
  // 12) 构建全局 slot 点集 allSlotPts（跨 topic），并绘制“全局 speaker 线”
  //     关键：每个点的 y 必须在对应 topic band 内，并且同 topic 内同 speaker 固定 y
  // ----------------------------
  type SlotPt = { id: number; topic: string; slot: string; source: string; x: number; y: number }

  // speaker -> frac(0..1)，用来在 band 内定位（全局一致）
  function buildSpeakerFrac(speakers: string[], padFrac = 0.12) {
    const frac = new Map<string, number>()
    const n = speakers.length
    if (n === 0) return frac
    if (n === 1) {
      frac.set(speakers[0], 0.5)
      return frac
    }
    const a = padFrac
    const b = 1 - padFrac
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1)
      frac.set(speakers[i], a + t * (b - a))
    }
    return frac
  }
  const speakerFrac = buildSpeakerFrac(allSpeakers, 0.12)

  const PAD_PX = 3

  // 生成 allSlotPts：对每个 slot，用它所属 topic 的 band 来算 y
  const allSlotPts: SlotPt[] = []
  for (const conv of convJson as any[]) {
    const topic = (conv.topic ?? 'Unknown').toString()
    const bandMap = bandByTopic.get(topic)
    if (!bandMap) continue

    for (const s of (conv.slots ?? []) as any[]) {
      const id = Number(s.id)
      if (!Number.isFinite(id)) continue

      const band = bandMap.get(id)
      if (!band) continue

      const source = (s.source ?? 'Unknown').toString().trim()
      const slot = (s.slot ?? '未标注 Slot').toString()

      const h = band.bot - band.top
      const frac = speakerFrac.get(source) ?? 0.5
      const yPos =
        h <= 2 * PAD_PX + 2
          ? (band.top + band.bot) / 2
          : band.top + PAD_PX + frac * (h - 2 * PAD_PX)

      allSlotPts.push({
        id,
        topic,
        slot,
        source,
        x: x(id),
        y: yPos,
      })
    }
  }

  // 全局画线：按 speaker 分组（跨所有 topic）
  function drawGlobalSpeakerLines() {
    lineRoot.selectAll('*').remove()

    const bySpeakerAll = d3.group(allSlotPts, (d) => d.source)

    const lineGen = d3
      .line<SlotPt>()
      .x((d) => d.x)
      .y((d) => d.y)
      .curve(d3.curveMonotoneX)

    bySpeakerAll.forEach((pts, speaker) => {
      if (!speaker || pts.length < 2) return
      const sorted = pts.slice().sort((a, b) => a.id - b.id)

      lineRoot
        .append('path')
        .attr('class', 'speaker-line')
        .attr('d', lineGen(sorted)!)
        .attr('fill', 'none')
        .attr('stroke', speakerColorMap[speaker] ?? '#111')
        .attr('stroke-width', 1.6)
        .attr('stroke-opacity', 0.85)
        .style('pointer-events', 'none')
    })

    lineRoot.raise()
  }

  drawGlobalSpeakerLines()

  // 可选：画点+slot 文本（一直显示）
  function drawSlotLabels() {
    labelRoot.selectAll('*').remove()

    // ✅ 没选中 topic 就不画（默认隐藏）
    if (activeKeys.size === 0) return

    const pts = allSlotPts.filter((p) => activeKeys.has(p.topic))

    const gSlot = labelRoot
      .selectAll('g.slot')
      .data(pts, (d: any) => `${d.id}-${d.source}-${d.slot}-${d.topic}`)
      .enter()
      .append('g')
      .attr('class', 'slot')
      .attr('transform', (d: any) => `translate(${d.x},${d.y}) rotate(-90)`)
      .style('pointer-events', 'none')

    gSlot
      .append('circle')
      .attr('r', 3.0)
      .attr('fill', (d: any) => speakerColorMap[d.source] ?? '#111')
      .attr('fill-opacity', 0.95)

    gSlot
      .append('text')
      .attr('x', 6)
      .attr('y', 0)
      .attr('dominant-baseline', 'middle')
      .attr('font-size', 11)
      .attr('fill', '#111')
      .text((d: any) => d.slot)
  }

  // ----------------------------
  // 13) 主题图例（支持 Shift 多选）
  // ----------------------------
  const topicLegendG = svg
    .append('g')
    .attr('class', 'topic-legend')
    .attr('transform', `translate(${legendX},${legendY})`)

  const topicLegendH = legendPadding * 2 + (keys.length + 1) * legendItemH

  topicLegendG
    .append('rect')
    .attr('width', legendW)
    .attr('height', topicLegendH)
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

  const topicItems = topicLegendG
    .selectAll('g.legend-item')
    .data(keys)
    .enter()
    .append('g')
    .attr('class', 'legend-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 10 + (i + 1) * legendItemH})`,
    )
    .style('cursor', 'pointer')
    .on('click', (event, key) => {
      event.stopPropagation()
      const e = event as MouseEvent

      if (e.shiftKey) {
        if (activeKeys.has(key)) activeKeys.delete(key)
        else activeKeys.add(key)
      } else {
        if (activeKeys.size === 1 && activeKeys.has(key)) activeKeys.clear()
        else {
          activeKeys.clear()
          activeKeys.add(key)
        }
      }

      applySelection()
      updateTopicLegendStyle()
      drawSlotLabels()
    })

  topicItems
    .append('rect')
    .attr('width', legendBox)
    .attr('height', legendBox)
    .attr('rx', 2)
    .attr('ry', 2)
    .attr('fill', (k) => topicColor(k))

  topicItems
    .append('text')
    .attr('x', legendBox + 8)
    .attr('y', legendBox - 2)
    .attr('fill', '#333')
    .attr('font-size', 11)
    .text((k) => k)

  function updateTopicLegendStyle() {
    const hasSelection = activeKeys.size > 0
    topicItems.style('opacity', (k) => (!hasSelection ? 1 : activeKeys.has(k) ? 1 : 0.35))

    topicItems
      .selectAll('rect')
      .attr('stroke', (k) => (!hasSelection ? 'none' : activeKeys.has(k) ? '#111' : 'none'))
      .attr('stroke-width', (k) => (!hasSelection ? 0 : activeKeys.has(k) ? 1.2 : 0))
  }

  updateTopicLegendStyle()

  // ----------------------------
  // 14) 角色图例（放在主题图例下面）
  // ----------------------------
  const roleLegendGapY = 12
  const roleLegendX = legendX
  const roleLegendY = legendY + topicLegendH + roleLegendGapY

  const roleLegendG = svg
    .append('g')
    .attr('class', 'role-legend')
    .attr('transform', `translate(${roleLegendX},${roleLegendY})`)

  const roleLegendH = legendPadding * 2 + (allSpeakers.length + 1) * legendItemH

  roleLegendG
    .append('rect')
    .attr('width', legendW)
    .attr('height', roleLegendH)
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

  const roleItems = roleLegendG
    .selectAll('g.role-item')
    .data(allSpeakers)
    .enter()
    .append('g')
    .attr('class', 'role-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 10 + (i + 1) * legendItemH})`,
    )

  roleItems
    .append('circle')
    .attr('cx', 6)
    .attr('cy', 6)
    .attr('r', 5)
    .attr('fill', (name) => speakerColorMap[name] ?? '#111')

  roleItems
    .append('text')
    .attr('x', 18)
    .attr('y', 10)
    .attr('fill', '#333')
    .attr('font-size', 11)
    .text((name) => name)

  // ----------------------------
  // 15) rotate：把整套 plot 旋转 90 度（图例不转）
  // ----------------------------
  const SHIFT_LEFT = legendW + 20
  g.attr('transform', `translate(${margin.left + plotW - SHIFT_LEFT},${margin.top}) rotate(90)`)

  // 保证 overlay 层级
  // 画完所有东西后
  bandRoot.lower()
  overlayRoot.raise()
  lineRoot.raise()
  labelRoot.raise()
}
onMounted(() => {
  draw().catch(console.error)
})

watch(
  () => props.datasetKey,
  () => {
    draw().catch(console.error)
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

.capsule-body {
  width: 1000px;
  height: 1000px;
  margin-top: 0px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
}

.dataset-label {
  width: 1000px;
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-right: 200px;
  font-size: 28px;
  font-weight: 600;
  color: #111;
  letter-spacing: 2px;
  user-select: none;
}

/* 底部按钮 */
.bottom-left-btn,
.bottom-mid-btn,
.bottom-right-btn {
  position: absolute;
  bottom: 10px;
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
.bottom-left-btn:hover,
.bottom-mid-btn:hover,
.bottom-right-btn:hover {
  background-color: #0056b3;
}

.bottom-left-btn {
  right: 80%;
  transform: translateX(-80%);
}
.bottom-mid-btn {
  right: 50%;
  transform: translateX(-50%);
}
.bottom-right-btn {
  right: 20%;
  transform: translateX(-20%);
}
</style>

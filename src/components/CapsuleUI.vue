<template>
  <div class="capsule-container">
    <div ref="UIcontainer" class="capsule-body"></div>
    <button class="bottom-left-btn" @click="DeleteLine">清除线条</button>
    <button class="bottom-mid-btn" @click="AddTalk">新开分支</button>
    <button class="bottom-right-btn" @click="emit('toggle-dataset')">切换数据</button>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { ref, watch } from 'vue'
import type { Conversation, MessageItem, Point, Segment } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
const activeTopicKey = ref<string | null>(null)

//颜色代表图
const topicColorMap: Record<string, string> = {}
// KDE 带宽（按你之前 html 的设置）
const BANDWIDTH = 8
// 每个发言人一个颜色
const SPEAKER_PALETTE = ['#14B8A6', '#A3E635', '#C026D3', '#FB7185', '#0F172A']

// 存储真实对话
const speakerColorMap: Record<string, string> = {} // 发言人 -> 颜色
const turnScoreMap = new Map<number, number>() // turn id -> 信息量评分
const data = ref<Conversation[]>([])
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

const onSlotClick = (slotId: number) => {
  FileStore.selectedSlotId = slotId
}

// 清空函数
const clearUI = () => {
  data.value = []
}

// 高亮选中 topic 带
const highlightTopicBands = (activeTopic: string | null) => {
  // 选中所有 topic 带
  const bands = d3.selectAll<SVGPathElement, Segment[]>('path.topic-band')

  bands
    .interrupt() // 先打断旧动画，避免叠加
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
      if (!activeTopic || t !== activeTopic) {
        return 'translate(0,0) scale(1,1)'
      }
      return 'translate(0,0) scale(1,1)'
    })
}

// 新开分支
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

  // 如果你有 activeTopicKey，就再强调一下这条带
  if (activeTopicKey.value) {
    highlightTopicBands(activeTopicKey.value)
  }
}

// 清除线条
const DeleteLine = () => {
  d3.select('.slot-global-cloud').selectAll('.speaker-slot-line').remove()
}

// 切换数据
type DatasetKey = 'meeting' | 'xinli'
const props = defineProps<{ datasetKey: DatasetKey }>()
const emit = defineEmits<{ (e: 'toggle-dataset'): void }>()

const DATASETS: Record<DatasetKey, { convUrl: string; scoreUrl: string }> = {
  meeting: {
    convUrl: '/meeting_processed.json',
    scoreUrl: '/meeting_score.json',
  },
  xinli: {
    convUrl: '/xinli_result.json',
    scoreUrl: '/xinli_score.json',
  },
}
async function loadAndDraw(key: DatasetKey) {
  const { convUrl, scoreUrl } = DATASETS[key]

  const convResp = await fetch(convUrl)
  const convJson: Conversation[] = await convResp.json()

  const scoreResp = await fetch(scoreUrl)
  const scoreJson: Array<{ id: number; info_score: number }> = await scoreResp.json()

  turnScoreMap.clear()
  scoreJson.forEach((item) => turnScoreMap.set(item.id, item.info_score))

  // （建议）清掉旧的颜色/高亮状态，避免残留
  activeTopicKey.value = null
  selectedTopicMessages.value = []
  Object.keys(topicColorMap).forEach((k) => delete topicColorMap[k])
  Object.keys(speakerColorMap).forEach((k) => delete speakerColorMap[k])

  data.value = convJson
  drawUI(convJson, turnScoreMap)
}

// 绘制 UI：一个总条带 + 堆叠 topic 山形条带 + 右上角图例 + 全局 slot 云
function drawUI(dataArr: Conversation[], turnScoreMap: Map<number, number>) {
  if (!UIcontainer.value) return

  // 清空画布
  d3.select(UIcontainer.value).selectAll('*').remove()

  // ===== 1. 从 Conversation[] 抽出点：topic + turn(id) + slot =====
  const points: Point[] = []
  const topicsSet = new Set<string>()

  dataArr.forEach((conv) => {
    const topic = conv.topic ?? 'Unknown Topic'
    const slots = conv.slots ?? []
    topicsSet.add(topic)
    topicColorMap[topic] = conv.color // 记录颜色

    slots.forEach((s) => {
      if (typeof s.id !== 'number') return
      const speakerName = (s.source || 'Unknown').toString().trim()

      // 从 Map 中取分数，取不到就给一个默认值
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
      })
    })
  })

  const topics = Array.from(topicsSet)

  const scores = points.map((p) => p.info_score ?? 0.5)
  const scoreMin = d3.min(scores) ?? 0.2
  const scoreMax = d3.max(scores) ?? 1.0

  const widthScale = d3.scaleLinear().domain([scoreMin, scoreMax]).range([0.3, 1]) // 想更夸张就改成 [0.4, 1.4] 之类
  const getTurnWidthFactor = (id: number) => {
    const s = turnScoreMap.get(id)
    const score = s ?? (scoreMin + scoreMax) / 2
    return widthScale(score)
  }

  // ===== 2.x 为每个发言人分配颜色 =====
  const speakers = Array.from(new Set(points.map((p) => p.source).filter((name) => !!name)))
  speakers.sort()

  speakers.forEach((name, idx) => {
    if (!speakerColorMap[name]) {
      const color = SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length]
      speakerColorMap[name] = color
    }
  })

  //
  const allPoints = points // ⭐ 全局保留，用于 slot 云窗口过滤

  const globalMinTurn = d3.min(points, (d) => d.id) ?? 0
  const globalMaxTurn = d3.max(points, (d) => d.id) ?? 0
  const xs = d3.range(globalMinTurn, globalMaxTurn + 1)

  // ===== 2. 按 topic 分组，做 KDE =====
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

  // ===== 3. 主视图布局参数 =====
  const width = 1000
  const height = 1000
  const MARGIN = { top: 20, right: 20, bottom: 40, left: 200 }
  const innerWidth = width - MARGIN.left - MARGIN.right
  const innerHeight = height - MARGIN.top - MARGIN.bottom

  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  const yScaleTime = d3.scaleLinear().domain([globalMinTurn, globalMaxTurn]).range([0, innerHeight])
  const yAxis = d3.axisLeft(yScaleTime).ticks(10).tickFormat(d3.format('d')) // 这里 TS 会推断成 Axis<NumberValue>

  g.append('g')
    .attr('class', 'axis y-axis')
    .call(yAxis as d3.Axis<number>)

  g.append('text')
    .attr('class', 'axis-label')
    .attr('x', -40)
    .attr('y', innerHeight / 2)
    .attr('text-anchor', 'middle')
    .attr('transform', `rotate(-90, -40, ${innerHeight / 2})`)
    .attr('fill', '#555')
    .attr('font-size', 12)
    .text('时间（对话轮次）')

  // 条带位置
  const STRIP_WIDTH = Math.min(500, innerWidth - 100)
  const STRIP_LEFT = 40 // 离 y 轴留一点距离
  const STRIP_CENTER = STRIP_LEFT + STRIP_WIDTH / 2

  // ===== 3.0 统一生成“每一行的宽度”：块均值 + 块内插值 =====
  const totalSteps = xs.length
  const NUM_WIDTH_BLOCKS = Math.min(10, totalSteps)
  const BLOCK_SIZE = Math.ceil(totalSteps / NUM_WIDTH_BLOCKS)

  const rowProfile = new Map<number, { rowWidth: number; stripLeft: number; stripRight: number }>()

  // 先：每块的平均 factor
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

    // 如果这一块全是 NaN，就用 1（或用邻近块）兜底
    blockAvg[bi] = cnt ? sumFactor / cnt : 1
  }

  // 再：把块内每个 id 用 “cur -> next” 插值填进 rowProfile
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
      const tt = t * t * (3 - 2 * t) // smoothstep（更像河流的过渡）

      const factor = cur + (next - cur) * tt

      const rowWidth = STRIP_WIDTH * factor
      const halfWidth = rowWidth / 2
      const stripLeft = STRIP_CENTER - halfWidth
      const stripRight = STRIP_CENTER + halfWidth

      rowProfile.set(id, { rowWidth, stripLeft, stripRight })
    }
  }

  console.log('rowProfile:', rowProfile)

  // ===== 3.1 把每个时间步的总宽按占比分给各个 topic =====
  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  xs.forEach((id, idx) => {
    const rp = rowProfile.get(id)
    if (!rp) return // 有可能少数 id 不在任何块里，安全起见判断下

    const localWidth = rp.rowWidth
    const stripLeft = rp.stripLeft
    const stripRight = rp.stripRight

    const densities = topics.map((t) => topicGroup.get(t)!.values[idx]?.value ?? 0)

    const sumDensity = d3.sum(densities)
    if (!sumDensity || sumDensity <= 0) return

    const ALPHA = 2
    let weighted = densities.map((v) => (v > 0 ? Math.pow(v, ALPHA) : 0))
    let sumWeighted = d3.sum(weighted)
    // ⭐ fallback：如果这一行 KDE 全为 0，就平均分（或沿用上一行）
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

      // ⭐ 不要跳过，保证每个 topic 每行都有点（哪怕 wTopic=0）
      topicBands.get(topic)!.push({ id, left, right })
      cursor = right
    })

    // ⭐ 防止累计误差：把最后一个 topic 的 right 强行贴到 stripRight
    const lastTopic = topics[topics.length - 1]
    const arr = topicBands.get(lastTopic)!
    arr[arr.length - 1].right = stripRight
  })

  // 一个帮助函数：选中某个 topic 时，更新 selectedTopicMessages
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
    // ⭐ 每次选中 topic，同步更新高亮效果
    highlightTopicBands(topic)
  }

  // ===== 4. 右上角图例参数（主题图例 + 角色图例，两个独立小框） =====
  const legendWidth = 170
  const legendItemHeight = 18
  const legendPadding = 10

  // 主题图例高度：上边距 + 标题 + topics
  const topicLegendHeight = legendPadding * 2 + (1 + topics.length) * legendItemHeight

  // 角色图例参数：单独一个小框，放在主题图例右侧
  const roleLegendWidth = 130
  const roleLegendRows = 2
  const roleLegendHeight = legendPadding * 2 + (1 + roleLegendRows) * legendItemHeight

  // 主题图例左上角（在条带右侧）
  const topicLegendX = STRIP_LEFT + STRIP_WIDTH + 20
  const topicLegendY = 0

  // 角色图例左上角：紧挨着主题图例右侧
  const roleLegendX = topicLegendX
  const roleLegendY = topicLegendY + topicLegendHeight + 12

  // ===== 5. 全局 slot 云：直接绘制在条带内部 =====
  function showSlotCloud(topic: string, centerTurn: number, clickX: number) {
    // 1) 取出该 topic 下的所有 slot，按时间排序
    const allSlots = allPoints.filter((p) => p.topic === topic).sort((a, b) => a.id - b.id)

    if (!allSlots.length) {
      const emptyLayer = g.select<SVGGElement>('.slot-global-cloud')
      if (!emptyLayer.empty()) emptyLayer.style('display', 'none')
      return
    }

    const maxSlots = 40 // 看你愿意展示多少条，可调
    const lines = allSlots.slice(0, maxSlots)

    // 2) 初始化 / 清空图层
    let cloudLayer = g.select<SVGGElement>('.slot-global-cloud')
    if (cloudLayer.empty()) {
      cloudLayer = g.append('g').attr('class', 'slot-global-cloud')
    }

    // ⭐ 每次出现前：打断旧动画 + 先变成透明并稍微下移缩小一点
    cloudLayer
      .interrupt()
      .style('display', null)
      .style('opacity', 0)
      .attr('transform', 'translate(0, 12) scale(0.96)')

    cloudLayer.selectAll('*').remove()

    // 5) 在条带内部布局：沿 y = 时间轴，x 在条带内左右“飘散”
    const paddingX = 12
    const minX = STRIP_LEFT + paddingX
    const maxX = STRIP_LEFT + STRIP_WIDTH - paddingX

    // 以点击位置为中心，先 clamp 一下，确保在总条带内
    const centerX = Math.max(minX, Math.min(clickX, maxX))
    const baseOffset = 10 // 相邻词云在 x 方向的间距，可以自己调

    const minFont = 10
    const maxFont = 18
    const minOpacity = 0.35
    const maxOpacity = 1.0

    const slotGroups = cloudLayer
      .selectAll('g.slot-label')
      .data(lines)
      .enter()
      .append('g')
      .attr('class', 'slot-label')
      .attr('transform', (d: Point, i) => {
        // === 一左一右交错布局 ===
        // rank = 0 是距离最近的；1 第二近；2 第三近…
        const rank = i
        let offsetIndex = 0
        if (rank === 0) {
          // 第 1 个（最近）在中心
          offsetIndex = 0
        } else {
          const step = Math.ceil(rank / 2) // 第几“层”偏移：1,1,2,2,3,3...
          const side = rank % 2 === 1 ? 1 : -1 // 奇数在右，偶数在左
          offsetIndex = side * step
        }

        let x = centerX + offsetIndex * baseOffset

        // 再次 clamp，避免出条带
        x = Math.max(minX, Math.min(x, maxX))
        const y = yScaleTime(d.id)

        // ⭐ 把全局坐标存到数据里，方便后面连线用
        ;(d as any)._x = x
        ;(d as any)._y = y

        return `translate(${x}, ${y})`
      })
      .style('cursor', 'pointer')
      .on('click', (event, d: Point) => {
        event.stopPropagation()
        console.log('点击 slot：', d.slot, 'id:', d.id, 'source:', d.source)
        onSlotClick(d.id)
      })

    // ===== 在这里给同一发言者的 slot 画连接线 =====
    const lineGen = d3
      .line<[number, number]>()
      .x((p) => p[0])
      .y((p) => p[1])
      .curve(d3.curveMonotoneY) // 或者 Basis，看你喜欢

    // 按发言者分组
    const bySpeaker = d3.group(lines, (d) => d.source)

    bySpeaker.forEach((slotsOfSpeaker, speakerName) => {
      if (!speakerName) return
      if (!slotsOfSpeaker || slotsOfSpeaker.length < 2) return // 至少两点才连线

      // 按 id 排序，保证线是从早到晚
      const sorted = slotsOfSpeaker
        .slice()
        .sort((a, b) => a.id - b.id)
        .filter((d) => (d as any)._x != null && (d as any)._y != null)

      if (sorted.length < 2) return

      const coords: [number, number][] = sorted.map((d) => [(d as any)._x, (d as any)._y])

      cloudLayer
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
      .attr('fill-opacity', (d: Point, i) => {
        // 按顺序稍微衰减一下透明度，让上面的更突出（可选）
        const t = lines.length <= 1 ? 1 : 1 - i / (lines.length - 1)
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
      .attr('font-size', (d: Point, i) => {
        const t = lines.length <= 1 ? 1 : 1 - i / (lines.length - 1)
        return minFont + t * (maxFont - minFont)
      })
      .attr('fill-opacity', 1)
      .text((d: Point) => (d.is_question && d.resolved ? `${d.slot} ✅️` : d.slot))

    // ⭐ 淡入 + 位移动画
    cloudLayer
      .transition()
      .duration(450) // 可以再加大一点比如 600
      .ease(d3.easeCubicOut)
      .style('opacity', 1)
      .attr('transform', 'translate(0, 0) scale(1)')

    // 点击外部清除：淡出后再清空
    svg.on('click', () => {
      activeTopicKey.value = null
      highlightTopicBands(null)
      cloudLayer
        .interrupt()
        .transition()
        .duration(300)
        .ease(d3.easeCubicIn)
        .style('opacity', 0)
        .on('end', () => {
          cloudLayer.selectAll('*').remove()
        })
    })
  }

  // 总条带边框
  if (rowProfile.size > 0) {
    // 为了控制控制点数量，我们按步长抽几个 id 出来
    const idsArray = Array.from(rowProfile.keys()).sort((a, b) => a - b)

    const MAX_POINTS = 30 // 最多 30 个控制点就够流畅了
    const STEP = Math.max(1, Math.floor(idsArray.length / MAX_POINTS))

    const sampledIds: number[] = []
    for (let i = 0; i < idsArray.length; i += STEP) {
      sampledIds.push(idsArray[i])
    }
    // 确保最后一个也在
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

    g.append('path')
      .attr('class', 'strip-outline')
      .attr('d', outlinePathData!)
      .attr('fill', 'none')
      .attr('stroke', '#e0e0e0')
      .attr('stroke-width', 1.2)
  }

  // ===== 6. 为每个 topic 画一条连续山形条带，并绑定点击事件 =====
  topicBands.forEach((segments, topic) => {
    const color = topicGroup.get(topic)!.color

    const area = d3
      .area<Segment>()
      .y((d) => yScaleTime(d.id))
      .x0((d) => d.left) // ⭐ 直接用绝对坐标
      .x1((d) => d.right)
      .curve(d3.curveBasis)

    g.append('path')
      .datum(segments)
      .attr('class', 'topic-band')
      .attr('d', (d: Segment[]) => area(d) ?? '')
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
        // updateTopicZoom(next)

        if (next) {
          const [mx, my] = d3.pointer(event, gNode)
          const idFloat = yScaleTime.invert(my)
          const centerTurn = Math.round(idFloat)
          showSlotCloud(topic, centerTurn, mx - 30)
        } else {
          const cloudLayer = g.select<SVGGElement>('.slot-global-cloud')
          if (!cloudLayer.empty()) {
            cloudLayer.style('display', 'none')
          }
        }
      })
  })

  // ===== 7. 主题图例框（左侧） =====
  const topicLegendG = g
    .append('g')
    .attr('class', 'topic-legend')
    .attr('transform', `translate(${topicLegendX}, ${topicLegendY})`)

  // 主题图例背景
  topicLegendG
    .append('rect')
    .attr('width', legendWidth)
    .attr('height', topicLegendHeight)
    .attr('rx', 6)
    .attr('ry', 6)
    .attr('fill', 'rgba(255,255,255,0.9)')
    .attr('stroke', '#ccc')

  // 标题：主题图例
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

  // ===== 8. 角色图例框（右侧单独一个小框） =====
  const roleLegendG = g
    .append('g')
    .attr('class', 'role-legend')
    .attr('transform', `translate(${roleLegendX}, ${roleLegendY})`)

  // 角色图例背景
  roleLegendG
    .append('rect')
    .attr('width', roleLegendWidth)
    .attr('height', roleLegendHeight)
    .attr('rx', 6)
    .attr('ry', 6)
    .attr('fill', 'rgba(255,255,255,0.9)')
    .attr('stroke', '#ccc')

  // 标题：角色图例
  roleLegendG
    .append('text')
    .attr('x', legendPadding)
    .attr('y', legendPadding + 4)
    .attr('fill', '#333')
    .attr('font-size', 12)
    .attr('font-weight', '600')
    .text('角色图例')

  // 角色 / 发言人图例框里：
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
// 1D KDE
function computeKDE1D(
  samples: number[],
  xs: number[],
  bandwidth: number,
): { x: number; value: number }[] {
  const n = samples.length
  if (n === 0) {
    return xs.map((x) => ({ x, value: 0 }))
  }

  const h = bandwidth
  const invH = 1 / h
  const values = xs.map((x) => ({ x, value: 0 }))

  for (const t of samples) {
    for (const v of values) {
      const u = (v.x - t) * invH
      v.value += Math.exp(-0.5 * u * u) // 高斯核
    }
  }

  const normFactor = 1 / (n * h * Math.sqrt(2 * Math.PI))
  for (const v of values) {
    v.value *= normFactor
  }

  return values
}

// 监听 GPT 返回内容的变化
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

/* 现在没有顶部导航栏，只保留主画布 */
.capsule-body {
  width: 1000px;
  height: 900px;
  margin-top: 10px;
}

/* 按钮固定在底部居中 */
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

<template>
  <div class="capsule-container">
    <div ref="UIcontainer" class="capsule-body"></div>
    <button class="bottom-left-btn">清除线条</button>
    <button class="bottom-right-btn" @click="AddTalk">新开分支</button>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
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
const SPEAKER_PALETTE = [
  '#1976d2', // 蓝
  '#e65100', // 橙
  '#7b1fa2', // 紫
  '#00897b', // 青
  '#f9a825', // 黄
  '#d81b60', // 粉
  '#5d4037', // 棕
]

const speakerColorMap: Record<string, string> = {} // 发言人 -> 颜色
const turnScoreMap = new Map<number, number>() // turn id -> 信息量评分

const onSlotClick = (slotId: number) => {
  FileStore.selectedSlotId = slotId
}
// 存储真实对话
const data = ref<Conversation[]>([])
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

// 清空函数
const clearUI = () => {
  // 清空画布
  // d3.select(UIcontainer.value).selectAll('*').remove()
  data.value = []
  // 清空GPT的对话内容，监听GPT内容，会重新绘制空白画布
  // FileStore.clearGPTContent()
}
// 高亮选中 topic 带
const highlightTopicBands = (activeTopic: string | null) => {
  // 选中所有 topic 带
  const bands = d3.selectAll<SVGPathElement, Segment[]>('path.topic-band')

  bands
    .transition()
    .duration(200)
    .attr('fill-opacity', function () {
      const t = (this as SVGPathElement).getAttribute('data-topic')
      if (!activeTopic) {
        // 没有选中任何 topic，全部恢复正常不变淡
        return 0.85
      }
      // 选中的 topic 保持原 opacity，其它变淡
      return t === activeTopic ? 0.85 : 0.15
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

function smoothScoreMap(
  turnIds: number[],
  rawMap: Map<number, number>,
  windowSize: number,
): Map<number, number> {
  const half = Math.floor(windowSize / 2)

  // 先取原始分数数组（保证每个 id 有值）
  const rawVals: number[] = turnIds.map((id) => rawMap.get(id) ?? 0.5)
  const rawMin = d3.min(rawVals) ?? 0.2
  const rawMax = d3.max(rawVals) ?? 1.0

  // 第一步：局部最大（max pooling）
  const pooled: number[] = []
  for (let i = 0; i < turnIds.length; i++) {
    let localMax = -Infinity
    for (let j = i - half; j <= i + half; j++) {
      if (j < 0 || j >= turnIds.length) continue
      const v = rawVals[j]
      if (v > localMax) localMax = v
    }
    if (!Number.isFinite(localMax)) {
      localMax = rawVals[i] ?? 0.5
    }
    pooled.push(localMax)
  }

  // 第二步：把 pooled 再线性拉回到 [rawMin, rawMax]，保留原始的动态范围
  const pooledMin = d3.min(pooled) ?? rawMin
  const pooledMax = d3.max(pooled) ?? rawMax

  const result = new Map<number, number>()

  if (pooledMax === pooledMin) {
    // 极端情况：全都一样，就直接用原始分数
    turnIds.forEach((id, idx) => {
      result.set(id, rawVals[idx] ?? rawMin)
    })
  } else {
    turnIds.forEach((id, idx) => {
      const v = pooled[idx]
      const norm = (v - pooledMin) / (pooledMax - pooledMin) // [0,1]
      const rescaled = rawMin + norm * (rawMax - rawMin) // 映射回原区间
      result.set(id, rescaled)
    })
  }

  return result
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
  if (!points.length) {
    console.error('当前数据中没有有效的 slots.id')
    return
  }

  // 所有 turn id
  const turnIds = Array.from(new Set(points.map((p) => p.id))).sort((a, b) => a - b)

  // 原始 score 映射
  const rawTurnScoreMap = new Map<number, number>()
  turnIds.forEach((id) => {
    const related = points.filter((p) => p.id === id)
    if (related.length > 0) {
      const avg = related.reduce((acc, p) => acc + (p.info_score ?? 0.5), 0) / related.length
      rawTurnScoreMap.set(id, avg)
    } else {
      rawTurnScoreMap.set(id, 0.5)
    }
  })

  // ⭐ 用新的平滑函数（windowSize 可以先用 5，看效果不够顺再试 7）
  const smoothedScoreMap = smoothScoreMap(turnIds, rawTurnScoreMap, 3)

  // 宽度缩放：这里可以给稍微大一点的动态范围，比如 [0.5, 1.2]
  const rawScores: number[] = turnIds
    .map((id) => rawTurnScoreMap.get(id))
    .filter((v): v is number => typeof v === 'number')

  const scores = points.map((p) => p.info_score ?? 0.5)

  const scoreMin = d3.min(scores) ?? 0.2
  const scoreMax = d3.max(scores) ?? 1.0

  const widthScale = d3.scaleLinear().domain([scoreMin, scoreMax]).range([0.6, 1]) // 想更夸张就改成 [0.4, 1.4] 之类

  const getTurnWidthFactor = (id: number) => {
    const s = turnScoreMap.get(id)
    const score = s ?? (scoreMin + scoreMax) / 2
    return widthScale(score)
  }

  // ===== 2.x 为每个发言人分配颜色 =====
  const speakers = Array.from(new Set(points.map((p) => p.source).filter((name) => !!name)))

  // 可以先排序一下，让图例更稳定
  speakers.sort()

  speakers.forEach((name, idx) => {
    if (!speakerColorMap[name]) {
      const color = SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length]
      speakerColorMap[name] = color
    }
  })

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

  // ===== 3.1 把每个时间步的总宽按占比分给各个 topic =====
  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  xs.forEach((id, idx) => {
    const f = getTurnWidthFactor(id) // ⭐ 每一轮的宽度系数
    const localWidth = STRIP_WIDTH * f // ⭐ 实际宽度

    const stripLeft = STRIP_CENTER - localWidth / 2
    const stripRight = STRIP_CENTER + localWidth / 2

    const densities = topics.map((t) => topicGroup.get(t)!.values[idx]?.value ?? 0)
    const sum = d3.sum(densities)
    if (!sum || sum <= 0) return

    let cursor = stripLeft
    topics.forEach((topic, ti) => {
      const v = densities[ti]
      if (v <= 0) return
      const wTopic = (v / sum) * localWidth
      const left = cursor
      const right = cursor + wTopic
      topicBands.get(topic)!.push({ id, left, right })
      cursor = right
    })
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
    cloudLayer.style('display', null)
    cloudLayer.selectAll('*').remove()

    // const halfWindow = 20
    // const minTurn = Math.max(globalMinTurn, centerTurn - halfWindow)
    // const maxTurn = Math.min(globalMaxTurn, centerTurn + halfWindow)

    // // 1) 过滤同 topic、且 id 在窗口内的所有 slot
    // const slotsInWindow = allPoints.filter(
    //   (p) => p.topic === topic && p.id >= minTurn && p.id <= maxTurn,
    // )

    // // 2) 去重：按 id 排序，同名 slot 只保留第一次出现的
    // const slotMap = new Map<string, Point>()
    // slotsInWindow
    //   .slice()
    //   .sort((a, b) => a.id - b.id)
    //   .forEach((p) => {
    //     if (!slotMap.has(p.slot)) {
    //       slotMap.set(p.slot, p)
    //     }
    //   })

    // let allSlots = Array.from(slotMap.values())
    // if (!allSlots.length) {
    //   const emptyLayer = g.select<SVGGElement>('.slot-global-cloud')
    //   if (!emptyLayer.empty()) emptyLayer.style('display', 'none')
    //   return
    // }

    // // 3) 根据距离 centerTurn 的远近排序：越近越重要
    // allSlots = allSlots.sort((a, b) => {
    //   const da = Math.abs(a.id - centerTurn)
    //   const db = Math.abs(b.id - centerTurn)
    //   return da - db
    // })

    // const maxSlots = 12 // 条带内部可以稍微多一点
    // const lines = allSlots.slice(0, maxSlots)

    // // 4) 初始化 / 清空图层
    // let cloudLayer = g.select<SVGGElement>('.slot-global-cloud')
    // if (cloudLayer.empty()) {
    //   cloudLayer = g.append('g').attr('class', 'slot-global-cloud')
    // }
    // cloudLayer.style('display', null)
    // cloudLayer.selectAll('*').remove()

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
        return `translate(${x}, ${y})`
      })
      .style('cursor', 'pointer')
      .on('click', (event, d: Point) => {
        event.stopPropagation()
        console.log('点击 slot：', d.slot, 'id:', d.id, 'source:', d.source)
        onSlotClick(d.id)
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
        // const dist = Math.abs(d.id - centerTurn)
        // const norm = Math.max(0, 1 - dist / halfWindow)
        // return minOpacity + norm * (maxOpacity - minOpacity)
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
        // const dist = Math.abs(d.id - centerTurn)
        // const norm = Math.max(0, 1 - dist / halfWindow)
        // return minFont + norm * (maxFont - minFont)
      })
      .attr('fill-opacity', (d: Point, i) => {
        const t = lines.length <= 1 ? 1 : 1 - i / (lines.length - 1)
        return minOpacity + t * (maxOpacity - minOpacity)
        // const dist = Math.abs(d.id - centerTurn)
        // const norm = Math.max(0, 1 - dist / halfWindow)
        // return minOpacity + norm * (maxOpacity - minOpacity)
      })
      .text((d: Point) => (d.is_question && d.resolved ? `${d.slot} ✅️` : d.slot))

    // 点击外部清除
    svg.on('click', () => {
      activeTopicKey.value = null
      highlightTopicBands(null)
      cloudLayer.selectAll('*').remove()
    })
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

  // 总条带边框
  // === 建一个“河流轮廓”的 path，左右对称 ===
  const profile = xs.map((id) => {
    const widthFactor = getTurnWidthFactor(id)
    const rowWidth = STRIP_WIDTH * widthFactor
    const halfWidth = rowWidth / 2
    const y = yScaleTime(id)
    return {
      id,
      y,
      leftX: STRIP_CENTER - halfWidth,
      rightX: STRIP_CENTER + halfWidth,
    }
  })

  const leftEdge: [number, number][] = profile.map((d) => [d.leftX, d.y])
  const rightEdge: [number, number][] = profile
    .slice()
    .reverse()
    .map((d) => [d.rightX, d.y])

  const outlineLine = d3
    .line<[number, number]>()
    .x((p) => p[0])
    .y((p) => p[1])
    .curve(d3.curveBasis)

  const outlinePathData = outlineLine([...leftEdge, ...rightEdge, leftEdge[0]])

  g.append('path')
    .attr('class', 'strip-outline')
    .attr('d', outlinePathData!)
    .attr('fill', 'none')
    .attr('stroke', '#e0e0e0')
    .attr('stroke-width', 1.2)

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

onMounted(async () => {
  try {
    // 1. 先加载对话数据
    const convResp = await fetch('/meeting_processed.json')
    // const convResp = await fetch('/xinli-processed.json')
    console.log('response:', convResp)
    const convJson: Conversation[] = await convResp.json()
    data.value = convJson
    console.log('data:', data.value)

    // 2. 再加载打分文件
    const scoreResp = await fetch('/meeting_score.json')
    // const scoreResp = await fetch('/xinli_score.json')
    const scoreJson: Array<{ id: number; info_score: number }> = await scoreResp.json()
    scoreJson.forEach((item) => {
      turnScoreMap.set(item.id, item.info_score)
    })

    drawUI(data.value, turnScoreMap)
  } catch (error) {
    console.error('加载 JSON 文件失败：', error)
  }
})
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
  left: 10%;
  transform: translateX(-30%);
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

.bottom-right-btn {
  position: absolute;
  bottom: 10px;
  right: 30%;
  transform: translateX(-30%);
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

<template>
  <div class="capsule-container">
    <!-- 只有主画布 -->
    <div ref="UIcontainer" class="capsule-body"></div>

    <button class="bottom-left-btn" @click="ClearLines">清除线条</button>
    <button class="bottom-mid-btn" @click="AddTalk">新开分支</button>
    <button class="bottom-right-btn" @click="Enlarge">放大区域</button>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
import type { Conversation, MessageItem } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
const ROLE_COLOR = {
  user: '#1976d2', // 你可以换成自己喜欢的 user 颜色
  bot: '#e65100', // bot 的颜色
}

// 颜色代表图
const topicColorMap: Record<string, string> = {}

// KDE 带宽
const BANDWIDTH = 8

// 存储真实对话
const data = ref<Conversation[]>([])
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

const Enlarge = () => {
  console.log('放大区域：当前版本还没实现放大镜')
}

// 清空函数
const clearUI = () => {
  if (UIcontainer.value) d3.select(UIcontainer.value).selectAll('*').remove()
  FileStore.clearGPTContent()
  data.value = []
}

// 清空线条（现在其实不画 user-line/bot-line，只是占位）
const ClearLines = () => {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('.user-line, .bot-line, .topic-connection').remove()
}

// 新开分支：把当前选中的 topic 相关句子作为历史上下文
const AddTalk = () => {
  if (!selectedTopicMessages.value.length) {
    console.log('请先点击某个 topic（条带或图例）！')
    return
  }

  clearUI()
  FileStore.triggerRefresh()

  const history = selectedTopicMessages.value.map((m) => ({
    id: m.id,
    from: m.role === 'user' ? 'user' : 'bot',
    text: m.content,
  })) as MessageItem[]
  FileStore.setMessageContent(history)
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

// 绘制 UI：一个总条带 + 堆叠 topic 山形条带 + 右上角图例 + 全局 slot 云
function drawUI(dataArr: Conversation[]) {
  if (!UIcontainer.value) return

  // 清空画布
  d3.select(UIcontainer.value).selectAll('*').remove()

  // ===== 1. 从 Conversation[] 抽出点：topic + turn(id) + slot =====
  type Point = {
    topic: string
    slot: string
    turn: number
    topicColor: string
    source: 'user' | 'bot'
  }

  const points: Point[] = []
  const topicsSet = new Set<string>()

  dataArr.forEach((conv) => {
    const topic = conv.topic ?? 'Unknown Topic'
    const slots = conv.slots ?? []
    topicsSet.add(topic)
    topicColorMap[topic] = conv.color // 记录颜色

    slots.forEach((s) => {
      if (typeof s.id !== 'number') return
      const rawSource = (s.source || '').toString().toLowerCase()

      const isBot =
        rawSource === 'bot' ||
        rawSource === 'assistant' ||
        rawSource === 'ai' ||
        rawSource === '助手' ||
        rawSource === '系统'

      // ⭐ 这里明确声明：只能是 'user' 或 'bot'
      const source: 'user' | 'bot' = isBot ? 'bot' : 'user'

      points.push({
        topic,
        slot: s.slot ?? '未标注 Slot',
        turn: s.id,
        topicColor: conv.color || '#1f77b4',
        source,
      })
    })
  })

  const topics = Array.from(topicsSet)
  if (!points.length) {
    console.error('当前数据中没有有效的 slots.id')
    return
  }

  const allPoints = points // ⭐ 全局保留，用于 slot 云窗口过滤

  const globalMinTurn = d3.min(points, (d) => d.turn) ?? 0
  const globalMaxTurn = d3.max(points, (d) => d.turn) ?? 0
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
    const turns = Array.from(new Set(arr.map((d) => d.turn))).sort((a, b) => a - b)
    const values = computeKDE1D(turns, xs, BANDWIDTH)
    topicGroup.set(topic, { color: topicColor, values })
  })

  // ===== 3. 主视图布局参数 =====
  const width = 1000
  const height = 900

  const MARGIN = { top: 20, right: 260, bottom: 40, left: 60 }
  const innerWidth = width - MARGIN.left - MARGIN.right
  const innerHeight = height - MARGIN.top - MARGIN.bottom

  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)

  const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

  // Y：时间轴
  const yScaleTime = d3.scaleLinear().domain([globalMinTurn, globalMaxTurn]).range([0, innerHeight])

  const yAxis = d3.axisLeft(yScaleTime).ticks(10).tickFormat(d3.format('d'))
  g.append('g')
    .attr('class', 'axis y-axis')
    .call(yAxis as any)

  g.append('text')
    .attr('class', 'axis-label')
    .attr('x', -40)
    .attr('y', innerHeight / 2)
    .attr('text-anchor', 'middle')
    .attr('transform', `rotate(-90, -40, ${innerHeight / 2})`)
    .attr('fill', '#555')
    .attr('font-size', 12)
    .text('时间（对话轮次）')

  // 总条带宽度（略窄一点，在右侧留空间画图例和 slot 云）
  const STRIP_WIDTH = Math.min(540, innerWidth - 120)
  const STRIP_LEFT = 40 // 离 y 轴留一点距离

  // ===== 3.1 把每个时间步的总宽按占比分给各个 topic =====
  type Segment = {
    turn: number
    left: number
    right: number
  }

  const topicBands = new Map<string, Segment[]>()
  topics.forEach((t) => topicBands.set(t, []))

  xs.forEach((turn, idx) => {
    const densities = topics.map((t) => topicGroup.get(t)!.values[idx]?.value ?? 0)
    const sum = d3.sum(densities)
    if (!sum || sum <= 0) return

    let cursor = 0
    topics.forEach((topic, ti) => {
      const v = densities[ti]
      if (v <= 0) return
      const w = (v / sum) * STRIP_WIDTH
      const left = cursor
      const right = cursor + w
      topicBands.get(topic)!.push({ turn, left, right })
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
  const roleLegendX = topicLegendX + legendWidth + 16
  const roleLegendY = 0

  // ⭐ slot 云气泡基准位置：放在两个小框中高度较高的那个下方
  const legendBlockBottomY = Math.max(topicLegendHeight, roleLegendHeight)
  const bubbleBaseX = topicLegendX
  const bubbleBaseY = topicLegendY + legendBlockBottomY + 10

  // ===== 5. 全局 slot 云：根据 (topic, turn) 窗口显示 slot 名称 =====
  function showSlotCloud(topic: string, centerTurn: number, targetX: number, targetY: number) {
    // 1) 计算窗口 [turn-10, turn+10]，并与全局范围相交
    const halfWindow = 10
    const minTurn = Math.max(globalMinTurn, centerTurn - halfWindow)
    const maxTurn = Math.min(globalMaxTurn, centerTurn + halfWindow)

    // 2) 过滤 slots：同 topic 且 id 在窗口内
    const slotsInWindow = allPoints.filter(
      (p) => p.topic === topic && p.turn >= minTurn && p.turn <= maxTurn,
    )

    // 按 turn 排序，并按 slot 名去重（取最早出现的一条，带 source）
    const slotMap = new Map<string, Point>()
    slotsInWindow
      .slice()
      .sort((a, b) => a.turn - b.turn)
      .forEach((p) => {
        if (!slotMap.has(p.slot)) {
          slotMap.set(p.slot, p)
        }
      })

    const allLines = Array.from(slotMap.values())
    if (!allLines.length) {
      const emptyLayer = g.select<SVGGElement>('.slot-global-cloud')
      if (!emptyLayer.empty()) emptyLayer.style('display', 'none')
      return
    }
    const maxLines = 8
    const lines = allLines.slice(0, maxLines)

    // 如果没有 slot，就隐藏云
    let cloudLayer = g.select<SVGGElement>('.slot-global-cloud')
    // 第一次使用时创建图层，后续复用
    if (cloudLayer.empty()) {
      cloudLayer = g.append('g').attr('class', 'slot-global-cloud').style('pointer-events', 'none')
    }
    cloudLayer.style('display', null)
    cloudLayer.selectAll('*').remove()

    // 3) 计算气泡的位置和大小
    const bubbleWidth = legendWidth + 40 // 比图例稍宽一点
    const lineHeight = 16
    const fontSize = 11
    const padding = 8
    const bubbleHeight = padding * 2 + (lines.length + 1) * lineHeight // 多 1 行用于标题

    const bubbleX = bubbleBaseX
    const bubbleY = bubbleBaseY

    // 4) 气泡背景
    cloudLayer
      .append('rect')
      .attr('x', bubbleX)
      .attr('y', bubbleY)
      .attr('width', bubbleWidth)
      .attr('height', bubbleHeight)
      .attr('rx', 10)
      .attr('ry', 10)
      .attr('fill', '#ffffff')
      .attr('stroke', '#999')
      .attr('stroke-width', 1.2)
      .attr('opacity', 0.96)

    // 5) 标题（例如 “topic”），颜色跟条带一致，居中显示
    const title = `${topic}`
    const topicColor = topicGroup.get(topic)?.color ?? topicColorMap[topic] ?? '#333'
    cloudLayer
      .append('text')
      .attr('x', bubbleX + bubbleWidth / 2) // ⭐ 水平居中：气泡中心
      .attr('y', bubbleY + padding + 12) // 适当下移一点
      .attr('text-anchor', 'middle') // ⭐ 居中对齐
      .attr('fill', topicColor) // ⭐ 使用 topic 颜色
      .attr('font-size', fontSize + 5)
      .attr('font-weight', '600')
      .text(title)

    // 每一行：小圆点 + 文本
    const firstLineY = bubbleY + padding + 24 // 标题下面一点
    const lineGroups = cloudLayer
      .selectAll('g.slot-line-group')
      .data(lines)
      .enter()
      .append('g')
      .attr('class', 'slot-line-group')
      .attr(
        'transform',
        (_d, i) => `translate(${bubbleX + padding}, ${firstLineY + i * lineHeight})`,
      )

    // 圆点：根据 source 设置颜色
    lineGroups
      .append('circle')
      .attr('cx', 0)
      .attr('cy', 0)
      .attr('r', 4)
      .attr('fill', (d: any) => (d.source === 'bot' ? ROLE_COLOR.bot : ROLE_COLOR.user))

    // 文本：往右偏一点
    lineGroups
      .append('text')
      .attr('x', 10)
      .attr('y', 0)
      .attr('dominant-baseline', 'middle')
      .attr('fill', '#555')
      .attr('font-size', fontSize)
      .text((d: any) => d.slot)

    // 箭头：从气泡右侧中点连到点击点
    const arrowStartX = bubbleX + bubbleWidth
    const arrowStartY = bubbleY + bubbleHeight / 2

    cloudLayer
      .append('line')
      .attr('x1', arrowStartX)
      .attr('y1', arrowStartY)
      .attr('x2', targetX)
      .attr('y2', targetY)
      .attr('stroke', '#999')
      .attr('stroke-width', 1.2)
  }

  // ===== 6. 为每个 topic 画一条连续山形条带，并绑定点击事件 =====
  topicBands.forEach((segments, topic) => {
    const color = topicGroup.get(topic)!.color

    const area = d3
      .area<Segment>()
      .y((d) => yScaleTime(d.turn))
      .x0((d) => STRIP_LEFT + d.left)
      .x1((d) => STRIP_LEFT + d.right)
      .curve(d3.curveBasis)

    g.append('path')
      .datum(segments)
      .attr('class', 'topic-band')
      .attr('d', area as any)
      .attr('fill', color)
      .attr('fill-opacity', 0.85)
      .style('cursor', 'pointer')
      .on('click', (event) => {
        event.stopPropagation()
        updateSelectedTopic(topic)

        // ⭐ 根据点击位置计算 turn，并显示 slot 云
        const [mx, my] = d3.pointer(event, g.node() as any)
        const turnFloat = yScaleTime.invert(my)
        const centerTurn = Math.round(turnFloat)
        showSlotCloud(topic, centerTurn, mx, my)
      })
  })

  // 总条带边框
  g.append('rect')
    .attr('x', STRIP_LEFT)
    .attr('y', 0)
    .attr('width', STRIP_WIDTH)
    .attr('height', innerHeight)
    .attr('fill', 'none')
    .attr('stroke', '#e0e0e0')
    .attr('stroke-width', 1)

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

  const roleLegendItemsData = [
    { label: '用户 (user)', color: ROLE_COLOR.user },
    { label: 'AI (bot)', color: ROLE_COLOR.bot },
  ]

  const roleLegendItems = roleLegendG
    .selectAll('.role-legend-item')
    .data(roleLegendItemsData)
    .enter()
    .append('g')
    .attr('class', 'role-legend-item')
    .attr(
      'transform',
      (_d, i) => `translate(${legendPadding}, ${legendPadding + 8 + i * legendItemHeight})`,
    )

  roleLegendItems
    .append('circle')
    .attr('cx', 6)
    .attr('cy', 6)
    .attr('r', 5)
    .attr('fill', (d) => d.color)

  roleLegendItems
    .append('text')
    .attr('x', 18)
    .attr('y', 10)
    .attr('fill', '#333')
    .attr('font-size', 11)
    .text((d) => d.label)
}

// 监听 GPT 返回内容的变化
watch(
  () => FileStore.GPTContent,
  (content) => {
    console.log(typeof content)
    try {
      content = content.flat()
      console.log('content:', content)
      drawUI(content)
    } catch (err) {
      console.error('JSON 解析失败:', err)
    }
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    const response = await fetch('/ChatGPT-xinli-processed.json')
    console.log('response:', response)
    const json: Conversation[] = await response.json()
    data.value = json
    console.log('data:', data.value)
    drawUI(data.value)
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

.bottom-mid-btn {
  position: absolute;
  bottom: 10px;
  right: 50%;
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
.bottom-mid-btn:hover {
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

<template>
  <div class="capsule-container">
    <div class="nav-scroll-container">
      <svg ref="navContainer"></svg>
    </div>
    <div ref="UIcontainer" class="capsule-body"></div>
    <button class="bottom-left-btn" @click="ClearLines">清除线条</button>
    <button class="bottom-right-btn" @click="AddTalk">新开分支</button>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
import type { Conversation, Slot, MessageItem } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
const navContainer = ref<SVGSVGElement | null>(null)
const topicXMap: Record<string, number> = {}

const topicColorMap: Record<string, string> = {}
// 存储真实对话
const data = ref<Conversation[]>([])
const selectedTopicMessages = ref<{ id: number; role: string; content: string }[]>([])

// 🧩 胶囊路径生成函数
function capsulePath(cx: number, cy: number, rw: number, rh: number) {
  return `
    M ${cx - rw}, ${cy - rh + rw}
    a ${rw},${rw} 0 0 1 ${2 * rw},0
    v ${2 * (rh - rw)}
    a ${rw},${rw} 0 0 1 ${-2 * rw},0
    Z
  `
}

// 清空函数
const clearUI = () => {
  d3.select(UIcontainer.value).selectAll('*').remove()
  d3.select(navContainer.value).selectAll('*').remove()
  FileStore.clearGPTContent()
  data.value = []
}
// 清空线条
const ClearLines = () => {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('.user-line, .bot-line, .topic-connection').remove()
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
    from: m.role === 'user' ? 'user' : 'bot',
    text: m.content,
  })) as MessageItem[]
  console.log('历史上下文：', history)
  FileStore.setMessageContent(history)
}
// 优化X坐标函数
function optimizeTopicOrder(
  topics: string[],
  topicPoints: Record<string, { x: number; y: number }[]>,
): string[] {
  const topicStats = topics.map((topic) => {
    const points = topicPoints[topic] || []
    // console.log('points是 :', points)
    if (points.length === 0) return { topic, score: Infinity }

    // 计算 Y 的中位数
    const ys = points.map((p) => p.y)
    const score =
      ys.length > 0
        ? ys.reduce((sum, y) => sum + y, 0) / ys.length // 使用平均值
        : Infinity

    return { topic, score: score }
  })

  // score 小 → 上方 → X 更靠左
  topicStats.sort((a, b) => a.score - b.score)
  // console.log('topicStats是 :', topicStats)

  // 返回排序后的 topic 名称数组
  return topicStats.map((d) => d.topic)
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()
  if (navContainer.value) {
    d3.select(navContainer.value).selectAll('*').remove()
  }

  let activeTopic: string | null = null

  const width = 1024
  const height = 1200
  let beforeY = 70 // 前一个 topic 半径
  let currentY = 140 // 每个 topic 垂直间隔
  const spacing = 50 // 固定间距
  const xInterval = 120 // X 方向间隔
  const lineHeight = 20 // 让文字均匀分布在胶囊高度内
  const fontSize = 20 // 字体大小
  const padding = 10

  const topics = Array.from(new Set(data.map((d) => d.topic))) // 去重
  data.forEach((d) => {
    topicColorMap[d.topic] = d.color
  })

  // 创建胶囊
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')

  const onSlotClick = (slotId: number) => {
    FileStore.selectedSlotId = slotId
  }

  // 大胶囊点击事件
  const onTopicClick = (topicSlots: Slot[], topic: string) => {
    const slotToSelect =
      topicSlots.find((s) => s.source === 'user') || topicSlots.find((s) => s.source === 'bot')

    if (slotToSelect) {
      onSlotClick(slotToSelect.id)
    }

    if (!topic) return

    // 高亮选中 topic，其余变灰
    topicGroups
      .selectAll<SVGPathElement, Conversation>('path.topic')
      .transition()
      .duration(300)
      .attr('fill', (d) => (d.topic === topic ? topicColorMap[d.topic] : '#ccc'))

    // 获取该 topic 所有大胶囊中心点
    const centers: { cx: number; cy: number; w: number; h: number }[] = []
    topicGroups.each(function (d: Conversation) {
      if (d.topic === topic) {
        centers.push({ cx: d.cx!, cy: d.cy!, w: d.w!, h: d.h! })
      }
    })

    // 获取当前 topic 的所有消息
    selectedTopicMessages.value = data
      .filter((d) => d.topic === topic)
      .flatMap((d) =>
        d.slots.map((s) => ({
          id: s.id,
          role: s.source,
          content: s.sentence,
        })),
      )
  }

  // --------------------- 绘制大胶囊---------------------
  //
  const topicGroups = g
    .selectAll('g.topic-group')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'topic-group')

  const topicPoints: Record<string, { x: number; y: number }[]> = {}
  // 设置基础信息
  topicGroups.each(function (topicData) {
    const rh = topicData.topic.length * fontSize * 1.5
    const cx = topicXMap[topicData.topic]
    const cy = currentY

    // 保存到 topicPoints
    if (!topicPoints[topicData.topic]) topicPoints[topicData.topic] = []
    topicPoints[topicData.topic].push({ x: cx, y: cy })

    currentY = currentY + beforeY + rh / 2 + spacing
    beforeY = rh
  })

  // 优化顺序
  const optimizedTopics = optimizeTopicOrder(topics, topicPoints)

  // 更新 topicXMap 和 topicPoints 的 X
  optimizedTopics.forEach((topic, i) => {
    const newX = 110 + i * xInterval
    topicXMap[topic] = newX
    topicPoints[topic].forEach((p) => (p.x = newX))
  })
  // console.log('topicPoints是 :', topicPoints)

  currentY = 140
  // 绘制
  topicGroups.each(function (topicData) {
    const group = d3.select(this)
    const rw = (topicData.topic.length * fontSize * 0.8) / 2
    const rh = (topicData.topic.length * fontSize * 1.5) / 2

    const cx = topicXMap[topicData.topic]
    const cy = currentY

    // 保存原始大小和坐标
    topicData.w = rw
    topicData.h = rh
    topicData.cx = cx
    topicData.cy = cy

    group
      .append('path')
      .attr('class', 'topic')
      .attr('d', capsulePath(cx, cy, rw, rh))
      .attr('fill', topicColorMap[topicData.topic])
      .attr('fill-opacity', 0.9)
      .on('click', (event) => {
        event.stopPropagation()
        const topicKey = topicData.topic
        onTopicClick(topicData.slots, topicKey)
        // 如果已展开同一类 → 忽略；如果展开的是另一类 → 先销毁旧 overlay 并恢复旧基座
        if (activeTopic && activeTopic !== topicKey) {
          destroyOverlay(activeTopic, g)
          showBase(activeTopic, g)
          activeTopic = null
        }

        if (!activeTopic) {
          hideBase(topicKey, g)
          buildOverlay(topicKey, g, topicColorMap, lineHeight, fontSize, padding, onSlotClick, data)
          activeTopic = topicKey
        }
      })

    currentY = currentY + beforeY + rh / 2 + spacing
    beforeY = rh
  })
  // --------------------- 绘制 topic 文本 ---------------------
  const topicTextsGroup = g.append('g').attr('class', 'topic-text-group')
  topicTextsGroup
    .selectAll('g.topic-text')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'topic-text')
    .attr('opacity', 0.8)
    .attr('transform', (d) => `translate(${d.cx}, ${d.cy})`)
    .each(function (d) {
      const gText = d3.select(this)
      const chars = d.topic.split('')
      const startY = -((chars.length - 1) * lineHeight) / 2
      chars.forEach((char, i) => {
        gText
          .append('text')
          .attr('x', 0)
          .attr('y', startY + i * lineHeight)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('fill', '#fff')
          .attr('font-size', fontSize)
          .text(char)
      })
    })

  // -----------绘制顶部导航栏----------------
  if (!navContainer.value) return
  const navHeight = 40
  const navSvg = d3
    .select(navContainer.value)
    .attr('width', topics.length * 150) // 让 SVG 宽于容器，从而可以滚动
    .attr('height', 40)

  const navBar = navSvg.append('g').attr('class', 'nav-bar')

  // 每个导航项对应一个 topic
  const navItems = navBar
    .selectAll('.nav-item')
    .data(topics)
    .enter()
    .append('g')
    .attr('class', 'nav-item')
    .attr('transform', (d) => `translate(${topicXMap[d]}, ${navHeight / 2})`)

  // 胶囊样式导航背景
  navItems
    .append('rect')
    .attr('x', -60)
    .attr('y', -15)
    .attr('width', 120)
    .attr('height', 30)
    .attr('rx', 15)
    .attr('fill', (d) => topicColorMap[d])
    .attr('opacity', 0.8)
    .on('click', (event, d) => {
      const svgNode = svg.node()
      if (!svgNode) return

      const currentTransform = d3.zoomTransform(svgNode)
      const k = currentTransform.k
      const currentY = currentTransform.y

      // 找出该 topic 对应的大胶囊中心 cx
      const topicData = data.find((item) => item.topic === d)
      if (!topicData?.cx) return

      // ✅ 计算新的 translateX，使导航栏和大胶囊对齐
      const targetX = topicXMap[d]
      const newTranslateX = targetX - topicData.cx * k

      svg
        .transition()
        .duration(500)
        .call(zoom.transform, d3.zoomIdentity.translate(newTranslateX, currentY).scale(k))
    })

  // 导航文字
  navItems
    .append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '0.35em')
    .attr('fill', '#fff')
    .text((d) => d)

  // --------------------- 绘制用户/机器人曲线 ---------------------
  const drawLines = () => {
    const userPoints = [{ x: 100, y: 0 }]
    const botPoints = [{ x: 120, y: 0 }]

    data.forEach((topic) => {
      const { cx, cy, slots } = topic
      if (!cx || !cy) return
      const offset = 10
      const topicHeight = topic.h!
      const topY = cy - topicHeight / 2
      const bottomY = cy + topicHeight / 2
      const curveOffsetY = 10 // 控制曲线提前拐弯的距离
      if (slots.some((s) => s.source === 'user')) {
        // 上拐点（在大胶囊上方）
        userPoints.push({ x: cx - offset, y: topY - curveOffsetY })
        // 下拐点（在大胶囊下方）
        userPoints.push({ x: cx - offset, y: bottomY + curveOffsetY })
      }
      if (slots.some((s) => s.source === 'bot')) {
        botPoints.push({ x: cx + offset, y: topY - curveOffsetY })
        botPoints.push({ x: cx + offset, y: bottomY + curveOffsetY })
      }
    })

    const lineGen = d3
      .line<{ x: number; y: number }>()
      .x((d) => d.x)
      .y((d) => d.y)
      .curve(d3.curveMonotoneY)

    g.append('path')
      .datum(userPoints)
      .attr('d', lineGen)
      .attr('class', 'user-line')
      .attr('stroke', 'red')
      .attr('stroke-width', 4)
      .attr('fill', 'none')
      .attr('stroke-opacity', 0.7)

    g.append('path')
      .datum(botPoints)
      .attr('d', lineGen)
      .attr('class', 'bot-line')
      .attr('stroke', 'blue')
      .attr('stroke-width', 4)
      .attr('fill', 'none')
      .attr('stroke-opacity', 0.7)
  }
  drawLines()

  // --------------------- 缩放事件 ----------
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 3])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
    })

  // ---- 点击空白处恢复 ----
  svg.on('click', () => {
    if (!activeTopic) return
    destroyOverlay(activeTopic, g)
    showBase(activeTopic, g)
    activeTopic = null
    // 大胶囊恢复原色
    topicGroups
      .selectAll<SVGPathElement, Conversation>('path.topic')
      .transition()
      .duration(300)
      .attr('fill', (d) => topicColorMap[d.topic])
  })

  svg.call(zoom)

  // 隐藏某一类的“基座”大胶囊与文字
  function hideBase(topicKey: string, g: d3.Selection<SVGGElement, unknown, null, undefined>) {
    g.selectAll<SVGGElement, Conversation>('g.topic-group')
      .filter((d) => d.topic === topicKey)
      .style('visibility', 'hidden')
    g.selectAll<SVGGElement, Conversation>('g.topic-text')
      .filter((d) => d.topic === topicKey)
      .style('visibility', 'hidden')
  }
  // 显示某一类的“基座”大胶囊与文字
  function showBase(topicKey: string, g: d3.Selection<SVGGElement, unknown, null, undefined>) {
    g.selectAll<SVGGElement, Conversation>('g.topic-group')
      .filter((d) => d.topic === topicKey)
      .style('visibility', null)
    g.selectAll<SVGGElement, Conversation>('g.topic-text')
      .filter((d) => d.topic === topicKey)
      .style('visibility', null)
  }

  // 删除 overlay 层
  function destroyOverlay(
    topicKey: string,
    g: d3.Selection<SVGGElement, unknown, null, undefined>,
  ) {
    g.selectAll(`.overlay-${topicKey}`).remove()
  }

  // 绘制 overlay 层
  function buildOverlay(
    topicKey: string,
    g: d3.Selection<SVGGElement, unknown, null, undefined>,
    topicColorMap: Record<string, string>,
    lineHeight: number,
    fontSize: number,
    padding: number,
    onSlotClick: (id: number) => void,
    dataArr: Conversation[],
  ) {
    // 1) 收集该类所有实例（同名 topic 可能多段）
    const items = dataArr.filter((d) => d.topic === topicKey)
    if (!items.length) return

    // 2) 三趟排布（你的版本） —— 只对这一类做布局
    type GroupLayout = {
      topic: string
      cx: number
      cy: number
      rx: number
      slots: Slot[]
      bandTop: number
      bandBottom: number
    }
    const slotRH = (len: number) => (len * fontSize * 1.5) / 2
    const slotRW = (len: number, rx: number) => Math.min((len * fontSize * 0.7) / 2, rx * 0.9)
    const MIN_GAP = 12

    // —— 第1趟：尺寸+原始排布
    const layouts: GroupLayout[] = []
    items.forEach((it) => {
      const slots = (it.slots || []).map((s) => ({ ...s })) // 拷贝避免污染
      const cx = it.cx!,
        cy = it.cy!,
        rx = it.w!
      slots.forEach((s) => {
        const L = s.slot.length
        s.rw = slotRW(L, rx)
        s.rh = slotRH(L)
      })
      const total = slots.reduce((acc, s) => acc + s.rh! * 2 + padding, 0) + padding
      const newRy = Math.max(total / 2, 75)
      let yOffset = cy - newRy + padding
      slots.forEach((s) => {
        s.x = cx
        s.y = yOffset + s.rh!
        yOffset += s.rh! * 2 + padding
      })
      layouts.push({
        topic: it.topic,
        cx,
        cy,
        rx,
        slots,
        bandTop: cy - newRy,
        bandBottom: cy + newRy,
      })
    })

    // —— 第2趟：同类之间消重叠
    layouts.sort((a, b) => a.bandTop - b.bandTop)
    let curBottom = -Infinity
    for (const L of layouts) {
      if (L.bandTop < curBottom + MIN_GAP) {
        const delta = curBottom + MIN_GAP - L.bandTop
        L.bandTop += delta
        L.bandBottom += delta
        L.cy = (L.bandTop + L.bandBottom) / 2
        // 同步平移 slots
        L.slots.forEach((s) => {
          s.y = s.y! + delta
        })
      }
      curBottom = Math.max(curBottom, L.bandBottom)
    }

    // —— 第3趟：画 overlay 层（展开胶囊+小胶囊+文字）
    const layer = g.append('g').attr('class', `overlay-${topicKey}`).attr('opacity', 1)

    // 3.1 先画“展开的大胶囊”（宽度 rx 固定，高度用 band）
    layouts.forEach((L) => {
      const cyExp = (L.bandTop + L.bandBottom) / 2
      const ryExp = (L.bandBottom - L.bandTop) / 2
      layer
        .append('path')
        .attr('class', 'topic-expanded')
        .attr('d', capsulePath(L.cx, cyExp, L.rx, ryExp))
        .attr('fill', topicColorMap[topicKey])
        .attr('fill-opacity', 0.9)
    })

    // 3.2 再画小胶囊
    layouts.forEach((L) => {
      // slots
      const join = layer
        .selectAll<SVGPathElement, Slot>(`.slot-${L.topic}-${L.cx}-${L.cy}`)
        .data(L.slots)

      join
        .enter()
        .append('path')
        .attr('class', 'slot')
        .attr('d', (s) => capsulePath(s.x!, s.y!, s.rw!, s.rh!))
        .attr('fill', (s) => s.color)
        .attr('opacity', 0.95)
        .on('click', (_e, s) => onSlotClick(s.id))
    })

    // 3.3 竖排文字
    layouts.forEach((L) => {
      const texts = layer
        .selectAll<SVGGElement, Slot>(`.slot-text-${L.topic}-${L.cx}-${L.cy}`)
        .data(L.slots)
        .enter()
        .append('g')
        .attr('class', 'slot-text')
        .attr('transform', (s) => `translate(${s.x}, ${s.y})`)
        .style('pointer-events', 'none')

      texts.each(function (s) {
        const gText = d3.select(this)
        const chars = s.slot.split('')
        const startY = -((chars.length - 1) * lineHeight) / 2
        chars.forEach((char, i) => {
          gText
            .append('text')
            .attr('x', 0)
            .attr('y', startY + i * lineHeight)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('fill', '#fff')
            .attr('font-size', fontSize)
            .text(char)
        })
      })
    })
  }
}
// 监听GPT返回内容的变化
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
  { immediate: true }, // 如果已经有数据，则立即触发
)
onMounted(async () => {
  try {
    // 1. 读取JSON文件（注意路径！）
    const response = await fetch('/ChatGPT-DST-processed.json')
    console.log('response:', response)
    // 2. 解析为JS对象
    const json: Conversation[] = await response.json()
    data.value = json
    console.log('data:', data.value)
    // 3. 调用D3绘制函数
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
.nav-scroll-container {
  width: 1024px;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  scrollbar-width: none; /* Firefox 隐藏滚动条 */
  -ms-overflow-style: none; /* IE 隐藏滚动条 */
}
.nav-scroll-container::-webkit-scrollbar {
  display: none;
}

.nav-scroll-container::-webkit-scrollbar-thumb {
  background: rgba(150, 150, 150, 0.6);
  border-radius: 3px;
}

.capsule-body {
  width: 850px;
  height: 850px;
  margin-top: 10px;
}
/* 按钮固定在底部居中 */
.bottom-left-btn {
  position: absolute;
  bottom: 10px;
  left: 30%;
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
/* 按钮固定在底部居中 */
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

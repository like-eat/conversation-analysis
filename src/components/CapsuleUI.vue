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

//颜色代表图
const topicColorMap: Record<string, string> = {}

//导航栏宽度和中心点x坐标
const navWidths: Record<string, number> = {}
const navCentersX: Record<string, number> = {}

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
  FileStore.setMessageContent(history)
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()
  if (navContainer.value) {
    d3.select(navContainer.value).selectAll('*').remove()
  }

  let activeTopic: string | null = null

  const width = 1440
  const height = 1200
  const lineHeight = 10 // 让文字均匀分布在胶囊高度内
  const fontSize = 10 // 字体大小
  const padding = 10

  // 🔍 放大镜两条线的初始位置（先只画线，可拖动）
  let lensY1 = 300
  let lensY2 = 900

  const LENS_SCALE = 2.5

  // 用 canvas 比较稳定地测量文字宽度
  function measureTextWidth(text: string, font = `${navFontSize}px sans-serif`) {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')!
    ctx.font = font
    return ctx.measureText(text).width
  }

  const topics = Array.from(new Set(data.map((d) => d.topic))) // 去重
  data.forEach((d) => {
    topicColorMap[d.topic] = d.color
  })

  // 创建胶囊
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')
  const baseLayer = g.append('g').attr('class', 'base-layer') // 原始大胶囊、曲线都画在这里
  const lensLayer = g.append('g').attr('class', 'lens-layer') // 放大效果单独一层

  const redrawLens = () => {
    lensLayer.selectAll('*').remove()
    if (!activeTopic) return
    buildOverlay(
      activeTopic,
      lensLayer,
      topicColorMap,
      lineHeight,
      fontSize,
      padding,
      onSlotClick,
      data,
    )
  }
  // 拖拽行为：上下拖动线条，更新 y1 / y2
  function makeLineDrag(which: 'y1' | 'y2') {
    return d3
      .drag<SVGLineElement, unknown>()
      .on('start', (event: any) => {
        if (event.sourceEvent) event.sourceEvent.stopPropagation()
      })
      .on('drag', function (event: any) {
        let newY = event.y
        newY = Math.max(0, Math.min(height, newY))

        if (which === 'y1') {
          newY = Math.min(newY, lensY2 - 20)
          lensY1 = newY
        } else {
          newY = Math.max(newY, lensY1 + 20)
          lensY2 = newY
        }

        d3.select(this).attr('y1', newY).attr('y2', newY)

        // 【新增】拖动线时，更新放大层
        redrawLens()
      })
  }
  // 在 svg 上画出两条水平线
  svg
    .append('line')
    .attr('class', 'lens-line-1')
    .attr('x1', 0)
    .attr('x2', width)
    .attr('y1', lensY1)
    .attr('y2', lensY1)
    .attr('stroke', '#888')
    .attr('stroke-dasharray', '4,4')
    .attr('stroke-width', 8) // ⭐ 加粗，方便点中
    .attr('opacity', 0.4)
    .style('cursor', 'ns-resize')
    .style('pointer-events', 'stroke') // ⭐ 只在描边上响应事件
    .call(makeLineDrag('y1'))

  svg
    .append('line')
    .attr('class', 'lens-line-2')
    .attr('x1', 0)
    .attr('x2', width)
    .attr('y1', lensY2)
    .attr('y2', lensY2)
    .attr('stroke', '#888')
    .attr('stroke-dasharray', '4,4')
    .attr('stroke-width', 8)
    .attr('opacity', 0.4)
    .style('cursor', 'ns-resize')
    .style('pointer-events', 'stroke')
    .call(makeLineDrag('y2'))

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

  // -----------绘制顶部导航栏----------------
  const navHeight = 40
  const navFontSize = 14 // 导航文字字号
  const navPadX = 16 // 左右内边距

  // 先计算每个 topic 的胶囊宽度 & 导航中心 x
  let totalWidth = 0
  topics.forEach((t, i) => {
    const tw = measureTextWidth(t)
    const rectW = Math.ceil(tw + navPadX * 2) // 胶囊矩形宽度
    navWidths[t] = rectW
    // 该 item 的中心位置 = 上一个末尾 + 半个本宽 + 间距
    const cx =
      i === 0 ? rectW / 2 : navCentersX[topics[i - 1]] + navWidths[topics[i - 1]] / 2 + rectW / 2
    navCentersX[t] = cx
    totalWidth = cx + rectW / 2 // 累计出总宽
  })

  // 让 SVG 按总宽设置，容器会水平滚动
  const navSvg = d3
    .select(navContainer.value)
    .attr('width', Math.max(totalWidth, 1))
    .attr('height', navHeight)

  const navBar = navSvg.append('g').attr('class', 'nav-bar')

  // 每个导航项对应一个 topic（按计算好的中心 x 排布）
  const navItems = navBar
    .selectAll('.nav-item')
    .data(topics)
    .enter()
    .append('g')
    .attr('class', 'nav-item')
    .attr('transform', (d) => `translate(${navCentersX[d]}, ${navHeight / 2})`)
    .style('cursor', 'pointer')

  // 胶囊背景（使用各自宽度，居中对齐）
  navItems
    .append('rect')
    .attr('x', (d) => -navWidths[d] / 2)
    .attr('y', -15)
    .attr('width', (d) => navWidths[d])
    .attr('height', 30)
    .attr('rx', 15)
    .attr('fill', (d) => topicColorMap[d])
    .attr('opacity', 0.85)
    .on('click', (event, d) => {
      event.stopPropagation()
      const svgNode = svg.node()
      if (!svgNode) return

      // 只做视图对齐，保持你原有的主画布列定位逻辑
      const currentTransform = d3.zoomTransform(svgNode)
      const k = currentTransform.k
      const currentY = currentTransform.y

      const topicData = data.find((item) => item.topic === d)
      if (!topicData?.cx) return

      const targetX = navCentersX[d] // 主画布该列中心
      const newTranslateX = targetX - topicData.cx * k

      svg
        .transition()
        .duration(500)
        .call(zoom.transform, d3.zoomIdentity.translate(newTranslateX, currentY).scale(k))
    })

  // 导航文字（居中）
  navItems
    .append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '0.35em')
    .attr('fill', '#fff')
    .style('font-size', `${navFontSize}px`)
    .text((d) => d)

  // --------------------- 绘制大胶囊---------------------
  const topMargin = 50
  const bottomMargin = 50
  const usableHeight = height - topMargin - bottomMargin

  const topicGroups = baseLayer
    .selectAll('g.topic-group')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'topic-group')

  // 绘制
  topicGroups.each(function (topicData, i) {
    const group = d3.select(this)
    const rw = (topicData.topic.length * fontSize * 1) / 5
    const rh = (topicData.topic.length * fontSize * 1) / 5

    const cx = navCentersX[topicData.topic]
    // 第 i 个的中心 Y：从 topMargin 开始，到 height-bottomMargin 结束，平均铺开
    const step = usableHeight / Math.max(data.length, 1)
    const cy = topMargin + step * (i + 0.5)

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
          destroyOverlay(activeTopic)
          showBase(activeTopic)
          activeTopic = null
        }

        if (!activeTopic) {
          hideBase(topicKey)
          activeTopic = topicKey
          redrawLens()
        }
      })
  })

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

    baseLayer
      .append('path')
      .datum(userPoints)
      .attr('d', lineGen)
      .attr('class', 'user-line')
      .attr('stroke', 'red')
      .attr('stroke-width', 4)
      .attr('fill', 'none')
      .attr('stroke-opacity', 0.7)

    baseLayer
      .append('path')
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
    .on('zoom', (event) => {
      // 如果你以后还想保留“平移”效果，可以用 event.transform.x / y
      // 这里我把缩放强行固定为 1，防止大小变化
      const t = event.transform
      g.attr('transform', `translate(${t.x}, ${t.y}) scale(1)`)
    })
    .filter(() => false) // ⭐ 关键：禁止所有用户触发的 zoom 事件

  // 仍然要挂上 zoom，这样你在别的地方可以用 zoom.transform 做平移对齐
  svg.call(zoom)

  // ---- 点击空白处恢复 ----
  svg.on('click', () => {
    if (!activeTopic) return
    destroyOverlay(activeTopic)
    showBase(activeTopic)
    activeTopic = null
    // 大胶囊恢复原色
    topicGroups
      .selectAll<SVGPathElement, Conversation>('path.topic')
      .transition()
      .duration(300)
      .attr('fill', (d) => topicColorMap[d.topic])
  })

  // 隐藏某一类的“基座”大胶囊与文字
  function hideBase(topicKey: string) {
    baseLayer
      .selectAll<SVGGElement, Conversation>('g.topic-group')
      .filter((d) => d.topic === topicKey)
      .style('visibility', 'hidden')
    g.selectAll<SVGGElement, Conversation>('g.topic-text')
      .filter((d) => d.topic === topicKey)
      .style('visibility', 'hidden')
  }
  // 显示某一类的“基座”大胶囊与文字
  function showBase(topicKey: string) {
    baseLayer
      .selectAll<SVGGElement, Conversation>('g.topic-group')
      .filter((d) => d.topic === topicKey)
      .style('visibility', null)
    g.selectAll<SVGGElement, Conversation>('g.topic-text')
      .filter((d) => d.topic === topicKey)
      .style('visibility', null)
  }

  // 【修改】只清理 lensLayer 中对应 topic 的 overlay
  function destroyOverlay(topicKey: string) {
    lensLayer.selectAll(`.overlay-${topicKey}`).remove()
  }

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

    // 2) 把所有 slots 合并成一份（按 id 排好，保持时间顺序）
    type SlotEx = Slot & {
      x?: number
      y?: number
      yRaw?: number
      rw?: number
      rh?: number
      baseRw?: number
    }

    const allSlots: SlotEx[] = items
      .flatMap((it) => (it.slots || []).map((s) => ({ ...s }) as SlotEx))
      .sort((a, b) => (Number(a.id) || 0) - (Number(b.id) || 0))

    if (!allSlots.length) return

    // 3) 取一个基准的中心 X / 宽度（所有同类 topic 的 cx 本来就在同一列）
    const base = items[0]
    const cx = base.cx!
    const rx = base.w!

    // 【新增】放大层横向放大系数：大胶囊和小胶囊都比 overview 宽一些
    const rxLens = rx * LENS_SCALE // 放大层里用的“大胶囊半宽”

    // 这里保存原始小胶囊的宽度
    const slotRH = (len: number) => (len * fontSize * 1.2) / 5
    const slotRWBase = (len: number, rx: number) => Math.min((len * fontSize * 0.7) / 5, rx * 0.9)

    // 计算原始宽度
    allSlots.forEach((s) => {
      const L = s.slot.length
      s.baseRw = slotRWBase(L, rx) // 保存原始宽度
      s.rh = slotRH(L)
    })

    // 在一个虚拟坐标系中，从上到下排布，记录 yRaw
    let yCursor = padding
    allSlots.forEach((s) => {
      s.yRaw = yCursor + (s.rh || 0)
      yCursor += (s.rh || 0) * 2 + padding
    })

    const rawMin = d3.min(allSlots, (s) => s.yRaw!)!
    const rawMax = d3.max(allSlots, (s) => s.yRaw!)!
    const rawSpan = rawMax - rawMin || 1

    // 映射到“全屏展开”的纵向范围 [topMargin, height-bottomMargin]
    const outerTop = topMargin
    const outerBottom = height - bottomMargin
    const outerSpan = outerBottom - outerTop

    allSlots.forEach((s) => {
      const t = (s.yRaw! - rawMin) / rawSpan
      s.y = outerTop + t * outerSpan
      s.x = cx
    })

    // ------------------- 第 2 步：基于 Y1/Y2 做“窗口放大” -------------------
    const Y1 = lensY1
    const Y2 = lensY2
    const Lout = Y2 - Y1

    const C = (Y1 + Y2) / 2
    const innerHalf = Lout / (2 * LENS_SCALE)
    let a = C - innerHalf
    let b = C + innerHalf

    // 保证 inner 区间在可用区域内
    a = Math.max(outerTop, a)
    b = Math.min(outerBottom, b)
    const innerSpan = b - a || 1

    // 分段映射：
    //  - [outerTop, a]  → [outerTop, Y1]      （压缩上半部）
    //  - [a, b]         → [Y1, Y2]            （放大中间区域）
    //  - [b, outerBottom] → [Y2, outerBottom]（压缩下半部）
    const mapY = (y: number) => {
      if (y <= a) {
        if (a === outerTop) return outerTop
        const t = (y - outerTop) / (a - outerTop)
        return outerTop + t * (Y1 - outerTop)
      } else if (y >= b) {
        if (b === outerBottom) return outerBottom
        const t = (y - b) / (outerBottom - b)
        return Y2 + t * (outerBottom - Y2)
      } else {
        const t = (y - a) / innerSpan
        return Y1 + t * Lout
      }
    }

    allSlots.forEach((s) => {
      s.y = mapY(s.y!)
    })

    // ------------------- 第 3 步：宽度放大 -------------------
    // 根据 Y 坐标和放大区域，调整小胶囊的宽度

    allSlots.forEach((s) => {
      const y = s.y!
      const inLens = y >= Y1 && y <= Y2 // 只有在放大区域内的才变宽
      s.rw = (s.baseRw || 0) * (inLens ? LENS_SCALE : 1)
      s.rh = (s.rh || 0) * (inLens ? LENS_SCALE : 1)
    })

    // 根据变换后的 y，算出大胶囊的中心和半高
    const minY2 = d3.min(allSlots, (s) => s.y!)!
    const maxY2 = d3.max(allSlots, (s) => s.y!)!
    const cyLens = (minY2 + maxY2) / 2
    const ryLens = (maxY2 - minY2) / 2 + padding

    // ------------------- 第 4 步：绘制 overlay -------------------
    const layer = g.append('g').attr('class', `overlay-${topicKey}`).attr('opacity', 1)

    // ===== 3.1 放大区域的“大胶囊容器”（只覆盖 Y1~Y2） =====
    const maxRw = d3.max(allSlots, (s) => s.rw || 0) || rxLens
    const containerRw = maxRw + padding

    // 3.1 大胶囊（只有一个）
    layer
      .append('path')
      .attr('class', 'topic-expanded')
      .attr('d', capsulePath(cx, cyLens, rx, ryLens))
      .attr('fill', topicColorMap[topicKey])
      .attr('fill-opacity', 1)

    layer
      .append('rect')
      .attr('class', 'topic-lens-container')
      .attr('x', cx - containerRw)
      .attr('y', Y1)
      .attr('width', containerRw * 2)
      .attr('height', Y2 - Y1)
      .attr('rx', 20) // 圆角，让它看起来还是“胶囊感”
      .attr('fill', topicColorMap[topicKey])
      .attr('fill-opacity', 1) // 半透明，不要挡住小胶囊

    // ========== 3.3 只给「矩形区域内」的小胶囊加竖排文本 ==========
    const slotsInLens = allSlots.filter((s) => s.y! >= Y1 && s.y! <= Y2)
    const lensFontScale = LENS_SCALE
    const lensFontSize = fontSize * lensFontScale
    const lensLineHeight = lineHeight * lensFontScale

    // ✅ 让小胶囊高度完全由“文字真实占用空间”决定
    slotsInLens.forEach((s) => {
      const charsLen = (s.slot || '').length || 1

      // 竖排文字真实占用的总高度 ≈ (行距 * (n - 1)) + 字体高度
      const textTotalHeight = (Math.max(charsLen, 1) - 1) * lensLineHeight + lensFontSize

      // 小胶囊半高 = 总高度一半，再稍微乘一点 padding（比如 1.1）
      const minRh = textTotalHeight / 2

      s.rh = Math.max(s.rh || 0, minRh)
    })

    // 3.2 小胶囊
    layer
      .selectAll<SVGPathElement, SlotEx>('.slot')
      .data(allSlots)
      .enter()
      .append('path')
      .attr('class', 'slot')
      .attr('d', (s) => capsulePath(s.x!, s.y!, s.rw!, s.rh!)) // 用 rw（可能被放大）
      .attr('fill', (s) => s.color)
      .attr('opacity', 0.95)
      .on('click', (event, s) => {
        event.stopPropagation() // ⭐ 阻止冒泡到 svg
        onSlotClick(s.id) // 继续你的定位逻辑
      })

    layer
      .selectAll<SVGGElement, SlotEx>('.slot-text')
      .data(slotsInLens)
      .enter()
      .append('g')
      .attr('class', 'slot-text')
      .attr('transform', (s) => `translate(${s.x}, ${s.y})`)
      .style('pointer-events', 'none') // 不挡住点击
      .each(function (s) {
        const gText = d3.select(this)
        const chars = (s.slot || '').split('')

        // 竖排：让文本整体在小胶囊内垂直居中
        const startY = -((chars.length - 1) * lensLineHeight) / 2

        chars.forEach((char, i) => {
          gText
            .append('text')
            .attr('x', 0)
            .attr('y', startY + i * lensLineHeight)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('fill', '#fff')
            .attr('font-size', lensFontSize)
            .text(char)
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
  width: 1440px;
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

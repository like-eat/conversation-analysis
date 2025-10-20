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
const domainXMap: Record<string, number> = {}

const domainColorMap: Record<string, string> = {}
// 存储真实对话
const data = ref<Conversation[]>([])
const selectedDomainMessages = ref<{ id: number; role: string; content: string }[]>([])

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
  d3.select(UIcontainer.value).selectAll('.user-line, .bot-line, .domain-connection').remove()
}
// 新开分支
const AddTalk = () => {
  if (!selectedDomainMessages.value.length) {
    console.log('请先点击一个 domain！')
    return
  }

  // 一、清除绘制内容
  clearUI()
  FileStore.triggerRefresh()

  // 二、将选中的 domain 内容作为历史上下文
  const history = selectedDomainMessages.value.map((m) => ({
    id: m.id,
    from: m.role === 'user' ? 'user' : 'bot',
    text: m.content,
  })) as MessageItem[]
  console.log('历史上下文：', history)
  FileStore.setMessageContent(history)
}
// 优化X坐标函数
function optimizeDomainOrder(
  domains: string[],
  domainPoints: Record<string, { x: number; y: number }[]>,
): string[] {
  const domainStats = domains.map((domain) => {
    const points = domainPoints[domain] || []
    // console.log('points是 :', points)
    if (points.length === 0) return { domain, score: Infinity }

    // 计算 Y 的中位数
    const ys = points.map((p) => p.y)
    const score =
      ys.length > 0
        ? ys.reduce((sum, y) => sum + y, 0) / ys.length // 使用平均值
        : Infinity

    return { domain, score: score }
  })

  // score 小 → 上方 → X 更靠左
  domainStats.sort((a, b) => a.score - b.score)
  // console.log('domainStats是 :', domainStats)

  // 返回排序后的 domain 名称数组
  return domainStats.map((d) => d.domain)
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()
  if (navContainer.value) {
    d3.select(navContainer.value).selectAll('*').remove()
  }

  const width = 1024
  const height = 884
  let beforeY = 70 // 前一个 domain 半径
  let currentY = 140 // 每个 domain 垂直间隔
  const spacing = 50 // 固定间距
  const xInterval = 120 // X 方向间隔
  const lineHeight = 20 // 让文字均匀分布在椭圆高度内
  const fontSize = 20 // 字体大小
  const padding = 10

  let activeDomain: string | null = null

  const domains = Array.from(new Set(data.map((d) => d.domain))) // 去重
  data.forEach((d) => {
    domainColorMap[d.domain] = d.color
  })

  // 创建椭圆
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')

  const onSlotClick = (slotId: number) => {
    FileStore.selectedSlotId = slotId
    console.log('定位 slot id:', slotId)
  }

  // 大椭圆点击事件
  const onDomainClick = (domainSlots: Slot[], domain: string) => {
    const slotToSelect =
      domainSlots.find((s) => s.source === 'user') || domainSlots.find((s) => s.source === 'bot')

    if (slotToSelect) {
      onSlotClick(slotToSelect.id)
    }

    if (!domain) return

    // 判断是否重复点击
    const isSame = activeDomain === domain

    // 如果重复点击同一个 domain → 清除连接线 + 恢复颜色
    if (isSame) {
      g.selectAll('.domain-connection').remove()
      domainGroups
        .selectAll<SVGPathElement, Conversation>('path.domain')
        .transition()
        .duration(300)
        .attr('fill', (d) => domainColorMap[d.domain]) // 恢复原色
      activeDomain = null // 清除状态
      return
    }

    // 否则是新点击 → 先清除旧线
    g.selectAll('.domain-connection').remove()

    // 高亮选中 domain，其余变灰
    domainGroups
      .selectAll<SVGPathElement, Conversation>('path.domain')
      .transition()
      .duration(300)
      .attr('fill', (d) => (d.domain === domain ? domainColorMap[d.domain] : '#ccc'))

    // 获取该 domain 所有大胶囊中心点
    const centers: { cx: number; cy: number; w: number; h: number }[] = []
    domainGroups.each(function (d: Conversation) {
      if (d.domain === domain) {
        centers.push({ cx: d.cx!, cy: d.cy!, w: d.w!, h: d.h! })
      }
    })

    // 至少 2 个胶囊才画桥
    if (centers.length < 2) return

    // 曲线生成器
    const lineGenerator = d3
      .line<{ x: number; y: number }>()
      .x((d) => d.x)
      .y((d) => d.y)
      .curve(d3.curveBasis)

    // 遍历相邻两个胶囊
    for (let i = 0; i < centers.length - 1; i++) {
      const a = centers[i]
      const b = centers[i + 1]

      // Y方向距离
      const midY = (a.cy + b.cy) / 2

      // 让中间收紧、两端外扩
      const startOffset = a.w
      const midOffset = a.w * 0.5 // 收紧
      const endOffset = b.w

      // 左曲线点（相切 + 收腰）
      const leftpoints = [
        { x: a.cx - startOffset, y: a.cy },
        { x: (a.cx + b.cx) / 2 - midOffset, y: midY },
        { x: b.cx - endOffset, y: b.cy },
      ]

      // 右曲线点（镜像）
      const rightpoints = [
        { x: a.cx + startOffset, y: a.cy },
        { x: (a.cx + b.cx) / 2 + midOffset, y: midY },
        { x: b.cx + endOffset, y: b.cy },
      ]

      // 封闭路径
      const combinedPath = `
        M${leftpoints[0].x},${leftpoints[0].y}
        ${leftpoints
          .slice(1)
          .map((p) => `L${p.x},${p.y}`)
          .join(' ')}
        L${rightpoints[rightpoints.length - 1].x},${rightpoints[rightpoints.length - 1].y}
        ${rightpoints
          .slice(0, -1)
          .reverse()
          .map((p) => `L${p.x},${p.y}`)
          .join(' ')}
        Z
      `

      // 绘制单个桥形区域
      g.append('path')
        .attr('class', 'domain-connection')
        .attr('d', combinedPath)
        .attr('fill', domainColorMap[domain])
        .attr('fill-opacity', 0.5)
        .attr('stroke', domainColorMap[domain])
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.5)
        .attr('fill-rule', 'evenodd')
        .transition()
        .duration(500)
    }
    // 更新domain
    activeDomain = domain

    // 获取当前 domain 的所有消息
    selectedDomainMessages.value = data
      .filter((d) => d.domain === domain)
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
  const domainGroups = g
    .selectAll('g.domain-group')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'domain-group')

  const domainPoints: Record<string, { x: number; y: number }[]> = {}
  // 设置基础信息
  domainGroups.each(function (domainData) {
    const rh = domainData.domain.length * fontSize * 1.5
    const cx = domainXMap[domainData.domain]
    const cy = currentY

    // 保存到 domainPoints
    if (!domainPoints[domainData.domain]) domainPoints[domainData.domain] = []
    domainPoints[domainData.domain].push({ x: cx, y: cy })

    currentY = currentY + beforeY + rh / 2 + spacing
    beforeY = rh
  })

  // 优化顺序
  const optimizedDomains = optimizeDomainOrder(domains, domainPoints)

  // 更新 domainXMap 和 domainPoints 的 X
  optimizedDomains.forEach((domain, i) => {
    const newX = 110 + i * xInterval
    domainXMap[domain] = newX
    domainPoints[domain].forEach((p) => (p.x = newX))
  })
  // console.log('domainPoints是 :', domainPoints)

  currentY = 140
  // 绘制
  domainGroups.each(function (domainData) {
    const group = d3.select(this)
    const rw = (domainData.domain.length * fontSize * 0.8) / 2
    const rh = (domainData.domain.length * fontSize * 1.5) / 2

    const cx = domainXMap[domainData.domain]
    const cy = currentY

    // 保存原始大小和坐标
    domainData.w = rw
    domainData.h = rh
    domainData.cx = cx
    domainData.cy = cy

    group
      .append('path')
      .attr('class', 'domain')
      .attr('d', capsulePath(cx, cy, rw, rh))
      .attr('fill', domainColorMap[domainData.domain])
      .attr('fill-opacity', 0.9)
      .on('click', (event) => {
        event.stopPropagation()
        onDomainClick(domainData.slots, domainData.domain)
      })

    currentY = currentY + beforeY + rh / 2 + spacing
    beforeY = rh
  })
  // -----------绘制顶部导航栏----------------
  if (!navContainer.value) return
  const navHeight = 40
  const navSvg = d3
    .select(navContainer.value)
    .attr('width', domains.length * 150) // 让 SVG 宽于容器，从而可以滚动
    .attr('height', 40)

  const navBar = navSvg.append('g').attr('class', 'nav-bar')

  // 每个导航项对应一个 domain
  const navItems = navBar
    .selectAll('.nav-item')
    .data(domains)
    .enter()
    .append('g')
    .attr('class', 'nav-item')
    .attr('transform', (d) => `translate(${domainXMap[d]}, ${navHeight / 2})`)

  // 胶囊样式导航背景
  navItems
    .append('rect')
    .attr('x', -60)
    .attr('y', -15)
    .attr('width', 120)
    .attr('height', 30)
    .attr('rx', 15)
    .attr('fill', (d) => domainColorMap[d])
    .attr('opacity', 0.8)
    .on('click', (event, d) => {
      const svgNode = svg.node()
      if (!svgNode) return

      const currentTransform = d3.zoomTransform(svgNode)
      const k = currentTransform.k
      const currentY = currentTransform.y

      // 找出该 domain 对应的大胶囊中心 cx
      const domainData = data.find((item) => item.domain === d)
      if (!domainData?.cx) return

      // ✅ 计算新的 translateX，使导航栏和大胶囊对齐
      const targetX = domainXMap[d]
      const newTranslateX = targetX - domainData.cx * k

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

    data.forEach((domain) => {
      const { cx, cy, slots } = domain
      if (!cx || !cy) return
      const offset = 10
      const domainHeight = domain.h!
      const topY = cy - domainHeight / 2
      const bottomY = cy + domainHeight / 2
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

  // --------------------- 绘制 domain 文本 ---------------------
  const domainTextsGroup = g.append('g').attr('class', 'domain-text-group')
  const domainTexts = domainTextsGroup
    .selectAll('g.domain-text')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'domain-text')
    .attr('opacity', 0.8)
    .attr('transform', (d) => `translate(${d.cx}, ${d.cy})`)
    .each(function (d) {
      const gText = d3.select(this)
      const chars = d.domain.split('')
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

  // --------------------- 缩放事件 ----------
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 3])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
      // 先计算小胶囊的高度 => 计算大胶囊的高度 => 设置小胶囊的坐标
      const slotGroup = g.select('.slot-group')

      // 放大时绘制小胶囊
      if (event.transform.k >= 1.25 && slotGroup.empty()) {
        const newGroup = g.append('g').attr('class', 'slot-group').attr('opacity', 0)

        domainGroups.each(function (domainData) {
          const group = d3.select(this)
          const slots = domainData.slots
          const cx = domainData.cx!
          const cy = domainData.cy!

          // 计算小椭圆的宽度和高度
          slots.forEach((slot) => {
            const textLen = slot.slot.length
            slot.rw = Math.min((textLen * fontSize * 0.7) / 2, domainData.w! * 0.9)
            slot.rh = (textLen * fontSize * 1.5) / 2
          })

          // 更新大胶囊高度
          const totalSlotHeight = slots.reduce((sum, s) => sum + s.rh! * 2 + padding, 0) + padding
          const newRy = Math.max(totalSlotHeight / 2, 75)
          const newRx = domainData.w!

          group
            .select('path.domain')
            .transition()
            .duration(400)
            .attr('d', capsulePath(cx, cy, newRx, newRy))

          // 设置小胶囊坐标（垂直居中）
          let yOffset = cy - newRy + padding
          slots.forEach((slot) => {
            slot.x = cx
            slot.y = yOffset + slot.rh!
            yOffset += slot.rh! * 2 + padding
          })

          // 绘制小胶囊
          const slotCapsules = newGroup
            .selectAll(`.slot-${domainData.domain}`)
            .data(slots)
            .enter()
            .append('path')
            .attr('class', 'slot')
            .attr('d', (s) => capsulePath(s.x!, s.y!, s.rw!, s.rh!))
            .attr('fill', (s) => s.color)
            .attr('opacity', 0)
            .on('click', (e, s) => onSlotClick(s.id))
            .transition()
            .duration(400)
            .attr('opacity', 0.8)

          // 绘制小胶囊文字
          const slotTexts = newGroup
            .selectAll(`.slot-text-${domainData.domain}`)
            .data(slots)
            .enter()
            .append('g')
            .attr('class', 'slot-text')
            .attr('transform', (s) => `translate(${s.x}, ${s.y})`)
            .attr('opacity', 0)
            .each(function (s) {
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
            .transition()
            .duration(400)
            .attr('opacity', 0.8)
        })
        newGroup.transition().duration(300).attr('opacity', 1)
        domainTexts.transition().duration(300).attr('opacity', 0)
      } else if (event.transform.k < 1.25 && !slotGroup.empty()) {
        slotGroup.transition().duration(300).attr('opacity', 0).remove()

        // 恢复大胶囊
        domainGroups.each(function (domainData) {
          const group = d3.select(this)
          group
            .select('path.domain')
            .transition()
            .duration(400)
            .attr('d', capsulePath(domainData.cx!, domainData.cy!, domainData.w!, domainData.h!))
        })

        // 恢复 domain 文本
        domainTexts.transition().duration(300).attr('opacity', 0.8)
      }
    })

  // ---- 点击空白处恢复 ----
  svg.on('click', () => {
    g.selectAll('.domain-connection').remove()
    // 大胶囊恢复原色
    domainGroups
      .selectAll<SVGPathElement, Conversation>('path.domain')
      .transition()
      .duration(300)
      .attr('fill', (d) => domainColorMap[d.domain])
  })

  svg.call(zoom)
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
    const response = await fetch('/ChatGPT-DST-checkpoint.json')
    console.log('response:', response)
    // 2. 解析为JS对象
    const json = await response.json()
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

<template>
  <div class="capsule-container">
    <div ref="UIcontainer" class="capsule-body"></div>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
import type { Conversation, Slot } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
const domainXMap: Record<string, number> = {}

const domainColorMap: Record<string, string> = {}
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

// 根据 domainPoints 中的 Y 坐标中位数优化 domain 顺序
function optimizeDomainOrder(
  domains: string[],
  domainPoints: Record<string, { x: number; y: number }[]>,
): string[] {
  const domainStats = domains.map((domain) => {
    const points = domainPoints[domain] || []
    console.log('points是 :', points)
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

  console.log('domainStats是 :', domainStats)
  // 返回排序后的 domain 名称数组
  return domainStats.map((d) => d.domain)
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()

  const width = 1024
  const height = 884
  let beforeY = 70 // 前一个 domain 半径
  let currentY = 140 // 每个 domain 垂直间隔
  const spacing = 50 // 固定间距
  const xInterval = 120 // X 方向间隔
  const lineHeight = 20 // 让文字均匀分布在椭圆高度内
  const fontSize = 15 // 字体大小
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

    // 获取该 domain 所有大胶囊的中心点
    const points: { x: number; y: number }[] = []
    domainGroups.each(function (d: Conversation) {
      if (d.domain === domain) {
        points.push({ x: d.cx!, y: d.cy! })
      }
    })

    // 两个点才画线
    if (points.length < 2) return

    // 绘制平滑曲线
    const lineGenerator = d3
      .line<{ x: number; y: number }>()
      .x((d) => d.x)
      .y((d) => d.y)
      .curve(d3.curveMonotoneY)

    g.append('path')
      .datum(points)
      .attr('class', 'domain-connection')
      .attr('d', lineGenerator)
      .attr('stroke', domainColorMap[domain])
      .attr('stroke-width', 5)
      .attr('stroke-opacity', 0.5)
      .transition()
      .duration(400)

    // 更新domain
    activeDomain = domain
  }

  // --------------------- 绘制大胶囊---------------------
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

    currentY = currentY + beforeY + rh + spacing
    beforeY = rh
  })

  // 2️⃣ 优化顺序
  const optimizedDomains = optimizeDomainOrder(domains, domainPoints)

  // 3️⃣ 更新 domainXMap 和 domainPoints 的 X
  optimizedDomains.forEach((domain, i) => {
    const newX = 110 + i * xInterval
    domainXMap[domain] = newX
    domainPoints[domain].forEach((p) => (p.x = newX))
  })
  console.log('domainPoints是 :', domainPoints)

  currentY = 140
  // 绘制
  domainGroups.each(function (domainData) {
    const group = d3.select(this)
    const rw = domainData.domain.length * fontSize
    const rh = domainData.domain.length * fontSize * 1.5

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

    currentY = currentY + beforeY + rh + spacing
    beforeY = rh
  })
  // -----------绘制顶部导航栏----------------
  const navHeight = 40
  const navBar = svg.append('g').attr('class', 'nav-bar')

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
    const userPoints = [{ x: 90, y: 0 }]
    const botPoints = [{ x: 130, y: 0 }]

    data.forEach((domain) => {
      const { cx, cy, slots } = domain
      if (!cx || !cy) return
      const offset = 20
      const domainHeight = domain.h!
      const topY = cy - domainHeight / 2
      const bottomY = cy + domainHeight / 2
      const curveOffsetY = 30 // 控制曲线提前拐弯的距离
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
      .attr('stroke', 'red')
      .attr('stroke-width', 4)
      .attr('fill', 'none')
      .attr('stroke-opacity', 0.7)

    g.append('path')
      .datum(botPoints)
      .attr('d', lineGen)
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
            slot.rw = (textLen * fontSize) / 2
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
      drawUI(content)
    } catch (err) {
      console.error('JSON 解析失败:', err)
    }
  },
  { immediate: true }, // 如果已经有数据，则立即触发
)
onMounted(() => {})
</script>
<style scoped>
/* 可根据需要调整容器大小 */
div {
  width: 850px;
  height: 850px;
  margin-top: 10px;
}
</style>

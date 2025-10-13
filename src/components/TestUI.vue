<template>
  <div class="svg-container" ref="UIcontainer"></div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
import type { Conversation, Slot } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
// 🧩 胶囊路径生成函数
// 辅助：生成竖向胶囊路径（dw: dh: 半高）
function capsulePath(cx: number, cy: number, dw: number, dh: number) {
  return `
    M ${cx - dw}, ${cy - dh + dw}
    a ${dw},${dw} 0 0 1 ${2 * dw},0
    v ${2 * (dh - dw)}
    a ${dw},${dw} 0 0 1 ${-2 * dw},0
    Z
  `
}

// 小椭圆点击了哪个句子
const onSlotClick = (slotId: number) => {
  FileStore.selectedSlotId = slotId
  console.log('定位 slot id:', slotId)
}
// 大椭圆
const onDomainClick = (domainSlots: Slot[]) => {
  const slotToSelect =
    domainSlots.find((s) => s.source === 'user') || domainSlots.find((s) => s.source === 'bot')

  if (slotToSelect) {
    onSlotClick(slotToSelect.id)
  }
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return
  d3.select(UIcontainer.value).selectAll('*').remove()

  // 初始椭圆参数
  const width = 1024
  const height = 884
  let beforeY = 70 // 前一个 domain 半径
  let currentY = 140 // 每个 domain 垂直间隔
  const spacing = 100 // 固定间距
  const xInterval = 200 // X 方向间隔
  const lineHeight = 20 // 让文字均匀分布在椭圆高度内
  const fontSize = 15 // 字体大小
  const padding = 10

  const domains = Array.from(new Set(data.map((d) => d.domain))) // 去重

  // 给每个 domain 计算 X
  const domainXMap: Record<string, number> = {}
  domains.forEach((domain, i) => {
    domainXMap[domain] = 110 + i * xInterval // 110 是初始 X
  })

  const domainPoints: Record<string, { x: number; y: number }[]> = {}
  // domain对应color
  const domainColorMap: Record<string, string> = {}
  data.forEach((d) => {
    domainColorMap[d.domain] = d.color
  })

  // 创建椭圆
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')

  // --------------------- 绘制大胶囊---------------------
  const domainGroups = g
    .selectAll('g.domain-group')
    .data(data)
    .enter()
    .append('g')
    .attr('class', 'domain-group')

  domainGroups.each(function (domainData) {
    const group = d3.select(this)
    const dw = domainData.domain.length * fontSize
    const dh = domainData.domain.length * fontSize * 1.5
    const cx = domainXMap[domainData.domain]
    const cy = currentY

    // 保存原始大小和坐标
    domainData.w = dw
    domainData.h = dh
    domainData.cx = cx
    domainData.cy = cy
    domainData.x = cx
    domainData.y = cy

    // 大胶囊
    group
      .append('path')
      .attr('class', 'domain')
      .attr('d', capsulePath(cx, cy, dw, dh))
      .attr('fill', domainColorMap[domainData.domain])
      .attr('fill-opacity', 0.9)
      .on('click', () => onDomainClick(domainData.slots))

    // 保存中心点
    if (!domainPoints[domainData.domain]) domainPoints[domainData.domain] = []
    domainPoints[domainData.domain].push({ x: cx, y: cy })

    currentY = currentY + beforeY + dh + spacing
    beforeY = dh
  })

  // --------------------- 绘制 domain 直线 ---------------------
  const lineGenerator = d3
    .line<{ x: number; y: number }>()
    .x((d) => d.x)
    .y((d) => d.y)
    .curve(d3.curveLinear)

  Object.entries(domainPoints).forEach(([domain, points]) => {
    g.append('path')
      .datum(points)
      .attr('d', lineGenerator)
      .attr('stroke', domainColorMap[domain])
      .attr('stroke-width', 5)
      .attr('stroke-opacity', 0.5)
  })

  // --------------------- 绘制用户/机器人曲线 ---------------------
  const drawLines = () => {
    const userPoints = [{ x: 90, y: 0 }]
    const botPoints = [{ x: 130, y: 0 }]
    data.forEach((domain) => {
      const { x, y, slots } = domain
      if (!x || !y) return
      const offset = 20
      const domainHeight = domain.h!
      const topY = y - domainHeight / 2
      const bottomY = y + domainHeight / 2
      const curveOffsetY = 30 // 控制曲线提前拐弯的距离
      if (slots.some((s) => s.source === 'user')) {
        // 上拐点（在大胶囊上方）
        userPoints.push({ x: x - offset, y: topY - curveOffsetY })
        // 下拐点（在大胶囊下方）
        userPoints.push({ x: x - offset, y: bottomY + curveOffsetY })
      }
      if (slots.some((s) => s.source === 'bot')) {
        botPoints.push({ x: x + offset, y: topY - curveOffsetY })
        botPoints.push({ x: x + offset, y: bottomY + curveOffsetY })
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
    .attr('transform', (d) => `translate(${d.x}, ${d.y})`)
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
    .scaleExtent([0.5, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
      const slotGroup = g.select('.slot-group')
      // 放大时绘制小胶囊
      if (event.transform.k >= 1.25 && slotGroup.empty()) {
        const newGroup = g.append('g').attr('class', 'slot-group').attr('opacity', 0)

        domainGroups.each(function (domainData) {
          const group = d3.select(this)
          const slots = domainData.slots
          const cx = domainData.cx!
          const cy = domainData.cy!

          // 布局小胶囊
          let yOffset = cy - domainData.h! + padding
          slots.forEach((slot) => {
            const textLen = slot.slot.length
            slot.dw = (textLen * fontSize) / 2
            slot.dh = (textLen * fontSize * 1.5) / 2
            slot.x = cx
            slot.y = yOffset + slot.dh!
            yOffset += slot.dh! * 2 + padding
          })
          // 更新大胶囊高度
          const totalSlotHeight = slots.reduce((sum, s) => sum + s.dh! * 2 + padding, 0) + padding
          const newRy = totalSlotHeight / 2
          const newRx = domainData.w!

          group
            .select('path.domain')
            .transition()
            .duration(400)
            .attr('d', capsulePath(cx, cy, newRx, newRy))

          // 绘制小胶囊
          const slotCapsules = newGroup
            .selectAll(`.slot-${domainData.domain}`)
            .data(slots)
            .enter()
            .append('path')
            .attr('class', 'slot')
            .attr('d', (s) => capsulePath(s.x!, s.y!, s.dw!, s.dh!))
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
input {
  margin-bottom: 10px;
}
</style>

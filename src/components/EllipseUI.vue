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

  // 清空上一次生成的 SVG
  d3.select(UIcontainer.value).selectAll('*').remove()

  // 初始椭圆参数
  const width = 1024
  const height = 884
  // 中心点
  let beforeY = 70 // 前一个 domain 半径
  let currentY = 140 // 每个 domain 垂直间隔
  const spacing = 100 // 固定间距

  // 假设 data 是 Conversation[]，每个元素有 domain 字段
  const domains = Array.from(new Set(data.map((d) => d.domain))) // 去重
  // X 方向间隔
  const xInterval = 200
  // 给每个 domain 计算 X
  const domainXMap: Record<string, number> = {}
  domains.forEach((domain, i) => {
    domainXMap[domain] = 110 + i * xInterval // 100 是初始 X
  })
  // 椭圆的中心点
  const domainPoints: Record<string, { x: number; y: number }[]> = {}
  // 颜色map
  const domainColorMap: Record<string, string> = {}
  data.forEach((d) => {
    domainColorMap[d.domain] = d.color
  })

  // 创建椭圆
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g') // 所有图形都在 g 里，方便缩放
  // 绘制大椭圆，并计算小椭圆位置
  const ellipsesData = data.map((domainData) => {
    const baseRx = 80
    const baseRy = 100
    const scale = 1 + 0.1 * (domainData.slots.length - 1)
    const domainRadiusX = baseRx * scale
    const domainRadiusY = baseRy * scale
    const cx = domainXMap[domainData.domain]
    const cy = currentY

    // 存入 Conversation 坐标
    domainData.x = cx
    domainData.y = cy

    const domainEllipse = g
      .append('ellipse')
      .attr('cx', cx)
      .attr('cy', cy)
      .attr('rx', domainRadiusX)
      .attr('ry', domainRadiusY)
      .attr('fill', domainColorMap[domainData.domain])
      .attr('fill-opacity', 0.9)
      .on('click', () => {
        console.log('点击了 domain:', domainData.domain)
        onDomainClick(domainData.slots)
      })

    // 将椭圆的中心点push进去
    if (!domainPoints[domainData.domain]) {
      domainPoints[domainData.domain] = []
    }
    domainPoints[domainData.domain].push({
      x: domainXMap[domainData.domain],
      y: currentY,
    })

    const domain = domainData.domain
    const lineHeight = 20 // 让文字均匀分布在椭圆高度内
    const textHeight = domain.length * lineHeight // 总高度
    const startY = currentY - textHeight / 2 // 从中心往上偏移一半

    domain.split('').forEach((char, i) => {
      g.append('text')
        .attr('x', domainXMap[domainData.domain]) // 椭圆左边，留 10px 间距
        .attr('y', startY + lineHeight / 2 + i * lineHeight) // 从椭圆顶端开始往下排
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', 16)
        .text(char)
    })

    // 绘制直线连接椭圆
    const lineGenerator = d3
      .line<{ x: number; y: number }>()
      .x((d) => d.x)
      .y((d) => d.y)
      .curve(d3.curveLinear) // 直线，你也可以换成 curveMonotoneY

    Object.entries(domainPoints).forEach(([domain, points]) => {
      g.append('path')
        .datum(points)
        .attr('d', lineGenerator)
        .attr('stroke', domainColorMap[domain]) // 这里你可以用 domainData.color
        .attr('stroke-width', 5)
        .attr('stroke-opacity', 0.5)
    })

    const slots = domainData.slots.map((slotData, i) => {
      const padding = 10
      let slotWidth: number
      let slotHeight: number
      let y: number
      if (domainData.slots.length === 1) {
        // 🔹只有一个小椭圆时，固定大小
        slotWidth = domainRadiusX * 0.6
        slotHeight = domainRadiusY * 0.6
        y = currentY
      } else {
        const availableHeight = domainRadiusY * 2 - padding * (domainData.slots.length + 1)
        slotWidth = domainRadiusX * 0.6
        slotHeight = availableHeight / domainData.slots.length
        y = currentY - domainRadiusY + padding + slotHeight / 2 + i * (slotHeight + padding)
      }

      const x = domainXMap[domainData.domain]

      return {
        ...slotData,
        x,
        y,
        rx: slotWidth / 2,
        ry: slotHeight / 2,
      }
    })

    currentY = currentY + beforeY + domainRadiusY + spacing
    beforeY = domainRadiusY

    domainData.slots = slots

    return { domainEllipse, slots }
  })

  // 绘制user/bot曲线
  const drawLines = () => {
    const userPoints = [{ x: 85, y: 0 }]
    const botPoints = [{ x: 130, y: 0 }]

    data.forEach((domain) => {
      const { x, y, slots } = domain
      if (!x || !y) return // 防止意外未定义

      const hasUser = slots.some((s) => s.source === 'user')
      const hasBot = slots.some((s) => s.source === 'bot')

      // 偏移量（左右偏 20）
      const offset = 20

      if (hasUser) {
        userPoints.push({ x: x - offset, y })
      }

      if (hasBot) {
        botPoints.push({ x: x + offset, y })
      }
    })
    console.log('Domain Points:', domainPoints)
    console.log('User Points:', userPoints)
    console.log('Bot Points:', botPoints)

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

  // 小椭圆组，初始透明度为 0
  const slotsGroup = g.append('g')
  const slotEllipses = slotsGroup
    .selectAll('ellipse')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('ellipse')
    .attr('data-slot-id', (d) => d.id)
    .on('click', (event, d) => onSlotClick(d.id))
    .attr('cx', (d) => d.x)
    .attr('cy', (d) => d.y)
    .attr('rx', (d) => d.rx) // 固定大小
    .attr('ry', (d) => d.ry) // 固定大小
    .attr('fill', (d) => d.color)
    .attr('opacity', 0) // 初始透明

  // 在小椭圆中心添加文字
  const slotTexts = slotsGroup
    .selectAll('text')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('text')
    .attr('x', (d) => d.x)
    .attr('y', (d) => d.y)
    .attr('text-anchor', 'middle') // 水平居中
    .attr('dominant-baseline', 'middle') // 垂直居中
    .attr('fill', '#fff') // 字体颜色，可根据小椭圆背景色调整
    .attr('font-size', 15) // 字体大小，可调整
    .text((d) => d.slot) // 显示 slot 名称
    .attr('opacity', 0) // 初始与椭圆透明度一致

  // 缩放事件
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
      // 动态调整文字大小
      slotTexts.attr('font-size', 15 / event.transform.k) // 让文字随缩放反向缩放
      if (event.transform.k >= 1.25) {
        // 渐显
        slotEllipses.transition().duration(500).attr('opacity', 0.8)
        slotTexts.transition().duration(500).attr('opacity', 0.8)
      } else {
        // 渐隐
        slotEllipses.transition().duration(500).attr('opacity', 0)
        slotTexts.transition().duration(500).attr('opacity', 0)
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
      // ====== 在这里给 domain 和 slot 顺序赋 ID ======
      let domainIdCounter = 1
      let slotIdCounter = 1
      const contentWithId = content.map((domain: Conversation) => {
        return {
          ...domain,
          id: domainIdCounter++,
          slots: domain.slots.map((slot) => ({
            ...slot,
            id: slotIdCounter++,
          })),
        }
      })
      drawUI(contentWithId)
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

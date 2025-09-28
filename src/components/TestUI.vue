<template>
  <div class="svg-container" ref="UIcontainer"></div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref } from 'vue'
import type { Conversation, Slot } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
// 小椭圆点击了哪个句子
const onSlotClick = (sentence: string) => {
  FileStore.selectedMessage = sentence
}
// 大椭圆点击
const onDomainClick = (domainSlots: Slot[]) => {
  if (domainSlots.length > 0) {
    onSlotClick(domainSlots[0].sentence)
  }
}
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return

  // 清空上一次生成的 SVG
  d3.select(UIcontainer.value).selectAll('*').remove()

  // 初始椭圆参数
  const width = 1024
  const height = 884
  // 中心点
  const currentX = width / 2
  let currentY = 70 // 每个 domain 垂直间隔

  // 创建椭圆
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)

  const g = svg.append('g') // 所有图形都在 g 里，方便缩放
  // 绘制大椭圆，并计算小椭圆位置
  const ellipsesData = data.map((domainData) => {
    const baseRx = 100
    const baseRy = 60
    const scale = 1 + 0.1 * (domainData.slots.length - 1)
    const domainRadiusX = baseRx * scale
    const domainRadiusY = baseRy * scale
    const domainEllipse = g
      .append('ellipse')
      .attr('cx', currentX)
      .attr('cy', currentY)
      .attr('rx', domainRadiusX)
      .attr('ry', domainRadiusY)
      .attr('fill', domainData.color)
      .attr('opacity', 0.5)
      .on('click', () => {
        console.log('点击了 domain:', domainData.domain)
        onDomainClick(domainData.slots)
      })
    // 在椭圆中心显示文字
    g.append('text')
      .attr('x', currentX)
      .attr('y', currentY - 30)
      .attr('text-anchor', 'middle') // 居中
      .attr('fill', '#fff') // 字体颜色，可根据背景调整
      .attr('font-size', 16) // 字体大小
      .text(domainData.domain)

    const slots = domainData.slots.map((slotData, i) => {
      const padding = 10
      let slotWidth: number
      let slotHeight: number
      let x: number
      if (domainData.slots.length === 1) {
        // 🔹只有一个小椭圆时，固定大小
        slotWidth = domainRadiusX * 0.6
        slotHeight = domainRadiusY * 0.6
        x = currentX
      } else {
        const availableWidth = domainRadiusX * 2 - padding * (domainData.slots.length + 1)
        slotWidth = availableWidth / domainData.slots.length
        slotHeight = domainRadiusY * 0.6 // 高度可以固定比例
        x = currentX - domainRadiusX + padding + slotWidth / 2 + i * (slotWidth + padding)
      }

      const y = currentY

      return {
        ...slotData,
        x,
        y,
        rx: slotWidth / 2,
        ry: slotHeight / 2,
      }
    })

    currentY += 200
    return { domainEllipse, slots }
  })

  // 小椭圆组，初始透明度为 0
  const slotsGroup = g.append('g')
  const slotEllipses = slotsGroup
    .selectAll('ellipse')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('ellipse')
    .on('click', (event, d) => {
      console.log('点击了 slot:', d.slot)
      onSlotClick(d.sentence)
    })
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

async function fetchExtractedData() {
  try {
    const response = await fetch('http://localhost:5000/test_extract')
    if (!response.ok) {
      throw new Error('网络请求失败')
    }
    const result = await response.json()
    console.log('后端返回数据:', result)

    // 存到 Pinia Store，触发 watch
    return result
  } catch (error) {
    console.error('请求出错:', error)
  }
}

onMounted(async () => {
  const data = await fetchExtractedData()
  if (data) {
    const newdata = data.flat()
    drawUI(newdata)
  }
})
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

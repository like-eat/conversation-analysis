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
const fontSize = 15
const lineHeight = 20
// 小胶囊点击了哪个句子
const onSlotClick = (slotId: number) => {
  FileStore.selectedSlotId = slotId
  console.log('定位 slot id:', slotId)
}
// 大胶囊
const onDomainClick = (domainSlots: Slot[]) => {
  const slotToSelect =
    domainSlots.find((s) => s.source === 'user') || domainSlots.find((s) => s.source === 'bot')

  if (slotToSelect) {
    onSlotClick(slotToSelect.id)
  }
}
// 辅助：生成竖向胶囊路径（rx: 水平半径，ry: 半高）
function capsulePath(cx: number, cy: number, rx: number, ry: number) {
  return `
    M ${cx - rx}, ${cy - ry + rx}
    a ${rx},${rx} 0 0 1 ${2 * rx},0
    v ${2 * (ry - rx)}
    a ${rx},${rx} 0 0 1 ${-2 * rx},0
    Z
  `
}

// 绘制 UI
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return

  // 清空 SVG
  d3.select(UIcontainer.value).selectAll('*').remove()

  const width = 1024
  const height = 884
  const fontSize = 15
  const spacing = 100
  let beforeY = 70
  let currentY = 140

  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')

  // 生成 domain 层级的唯一 id
  const ellipsesData = data.map((domainData, domainIdx) => {
    const domainId = `${domainData.domain}-${domainIdx}`

    const rx = fontSize * domainData.domain.length
    const ry = fontSize * domainData.domain.length * 1.5
    const cx = 110 + domainIdx * 200
    const cy = currentY

    // 大胶囊
    const domainCapsule = g
      .append('path')
      .attr('d', capsulePath(cx, cy, rx, ry))
      .attr('fill', domainData.color)
      .attr('fill-opacity', 0.9)
      .on('click', () => {
        const slotToSelect =
          domainData.slots.find((s) => s.source === 'user') ||
          domainData.slots.find((s) => s.source === 'bot')
        if (slotToSelect) FileStore.selectedSlotId = slotToSelect.id
      })

    // 大胶囊文字
    const domainTextGroup = g.append('g').attr('class', `domain-text-group domain-${domainId}`)

    const lineHeight = 20
    const textHeight = domainData.domain.length * lineHeight
    const startY = cy - textHeight / 2
    domainData.domain.split('').forEach((char, i) => {
      domainTextGroup
        .append('text')
        .attr('class', `domain-text domain-${domainId}`)
        .attr('x', cx)
        .attr('y', startY + lineHeight / 2 + i * lineHeight)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', fontSize)
        .text(char)
    })

    // 小胶囊
    const slots = domainData.slots.map((slot, slotIdx) => {
      const textLen = slot.slot.length
      const slotWidth = fontSize * textLen
      const slotHeight = Math.max(fontSize * textLen * 1.5, fontSize * 2)
      let y = cy
      if (domainData.slots.length > 1) {
        const padding = 10
        y = cy - ry + padding + slotHeight / 2 + slotIdx * (slotHeight + padding)
      }
      const slotId = `slot-${domainId}-${slotIdx}`
      const groupId = `slot-group-${domainId}-${slotIdx}`
      return {
        ...slot,
        x: cx,
        y,
        rx: slotWidth / 2,
        ry: slotHeight / 2,
        slotId,
        groupId,
        _slotHeight: slotHeight,
      }
    })

    currentY += beforeY + ry + spacing
    beforeY = ry

    return { domainData, domainId, domainCapsule, domainTextGroup, slots, cx, cy, rx, ry }
  })

  // 小胶囊组
  const slotsGroup = g.append('g').attr('class', 'slots-group')
  const slotEllipses = slotsGroup
    .selectAll('path.slot')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('path')
    .attr('class', 'slot')
    .attr('id', (d) => d.slotId)
    .attr('d', (d) => capsulePath(d.x, d.y, d.rx, d.ry))
    .attr('fill', (d) => d.color)
    .attr('opacity', 0)
    .on('click', (event, d) => onSlotClick(d.id))

  // 小胶囊文字组
  const slotGroups = slotsGroup
    .selectAll('g.slot-group')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('g')
    .attr('class', 'slot-group')
    .attr('id', (d) => d.groupId)

  slotGroups.each(function (d) {
    const gThis = d3.select(this)
    const chars = d.slot.split('')
    const startY = d.y - ((chars.length - 1) * lineHeight) / 2
    chars.forEach((char, i) => {
      gThis
        .append('text')
        .attr('x', d.x)
        .attr('y', startY + i * lineHeight)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', fontSize)
        .attr('opacity', 0)
        .text(char)
    })
  })

  // 缩放逻辑
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 3])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())

      ellipsesData.forEach((d) => {
        const { cx, cy, rx, ry, slots, domainCapsule, domainId } = d
        const originalRy = ry
        if (event.transform.k >= 1.25) {
          const padding = 10
          const totalHeight =
            slots.reduce((acc, s) => acc + s._slotHeight, 0) + padding * (slots.length - 1)
          const targetRy = Math.max(originalRy, totalHeight / 2 + rx * 0.25)
          domainCapsule
            .transition()
            .duration(300)
            .attr('d', capsulePath(cx, cy, rx, targetRy))

          // 小胶囊布局
          let currentTop = cy - totalHeight / 2
          slots.forEach((slot) => {
            const slotCenterY = currentTop + slot._slotHeight / 2
            currentTop += slot._slotHeight + padding
            d3.select(`#${slot.slotId}`)
              .transition()
              .duration(300)
              .attr('d', capsulePath(slot.x, slotCenterY, slot.rx, slot.ry))
              .attr('opacity', 0.9)
            const group = d3.select(`#${slot.groupId}`)
            const chars = slot.slot.split('')
            const startY = slotCenterY - ((chars.length - 1) * lineHeight) / 2
            group.selectAll('text').each((_, i, nodes) => {
              d3.select(nodes[i])
                .transition()
                .duration(300)
                .attr('y', startY + i * lineHeight)
                .attr('opacity', 1)
            })
          })

          // 隐藏大胶囊文字
          g.selectAll(`.domain-text.domain-${domainId}`)
            .transition()
            .duration(200)
            .style('opacity', 0)
        } else {
          // 缩小回去
          domainCapsule
            .transition()
            .duration(300)
            .attr('d', capsulePath(cx, cy, rx, ry))
          slots.forEach((slot) => {
            d3.select(`#${slot.slotId}`)
              .transition()
              .duration(250)
              .attr('d', capsulePath(slot.x, slot.y, slot.rx, slot.ry))
              .attr('opacity', 0)
            const group = d3.select(`#${slot.groupId}`)
            const chars = slot.slot.split('')
            const startY = slot.y - ((chars.length - 1) * lineHeight) / 2
            group.selectAll('text').each((_, i, nodes) => {
              d3.select(nodes[i])
                .transition()
                .duration(250)
                .attr('y', startY + i * lineHeight)
                .attr('opacity', 0)
            })
          })
          // 恢复大胶囊文字
          g.selectAll(`.domain-text.domain-${domainId}`)
            .transition()
            .delay(200)
            .duration(300)
            .style('opacity', 1)
        }
      })
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

<template>
  <div class="container">
    <div ref="svgContainer" class="svg-box"></div>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref } from 'vue'

const svgContainer = ref<HTMLDivElement | null>(null)
function drawUI() {
  if (!svgContainer.value) return

  const width = 100 // 胶囊的宽度（横向）
  const height = 240 // 胶囊的总高度（竖向）
  const r = width / 2 // 半圆半径（由宽度决定）

  // 清空容器
  d3.select(svgContainer.value).selectAll('*').remove()

  // 创建 SVG
  const svg = d3
    .select(svgContainer.value)
    .append('svg')
    .attr('width', 400)
    .attr('height', 500)
    .style('background', '#f9fafb')
    .style('border-radius', '12px')
    .style('cursor', 'grab')

  // 创建可缩放图层
  const zoomLayer = svg.append('g').attr('transform', 'translate(150,100)')

  // 定义竖向路径（上半圆 + 矩形 + 下半圆）
  const pathData = `
  M 0,${r}
  A ${r},${r} 0 0 1 ${width},${r}
  V ${height - r}
  A ${r},${r} 0 0 1 0,${height - r}
  Z
`

  // 绘制竖向胶囊
  zoomLayer
    .append('path')
    .attr('d', pathData)
    .attr('fill', '#4f46e5')
    .attr('stroke', '#1e1b4b')
    .attr('stroke-width', 2)

  // 添加竖直居中文本
  zoomLayer
    .append('text')
    .attr('x', width / 2)
    .attr('y', height / 2 + 5)
    .attr('text-anchor', 'middle')
    .attr('fill', 'white')
    .attr('font-size', '16px')
    .attr('writing-mode', 'vertical-rl') // 文本竖排
    .attr('text-orientation', 'upright')
    .text('竖向节点')

  // 定义缩放行为
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 3])
    .on('zoom', (event) => {
      zoomLayer.attr('transform', event.transform)
    })

  // 应用缩放
  svg.call(zoom)
}
onMounted(() => {
  drawUI()
})
</script>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 40px;
}
</style>

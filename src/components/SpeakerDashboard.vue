<template>
  <div class="dashboard-container">
    <!-- 未选中主题时的占位 -->
    <div v-if="activeTopics.length === 0" class="dashboard-placeholder">
      <span>点击上方主题查看发言占比</span>
    </div>

    <!-- 选中主题后：左右分栏 -->
    <template v-else>
      <div class="dashboard-left" ref="chartsContainer"></div>
      <div class="dashboard-right">
        <div class="placeholder-card">
          <span class="placeholder-icon">📊</span>
          <span class="placeholder-text">更多统计即将上线</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { ref, watch, onMounted, nextTick } from 'vue'
import type { Point } from '@/types/index'

const props = defineProps<{
  activeTopics: string[]
  allPoints: Point[]
  speakerColorMap: Record<string, string>
  topicColorMap: Record<string, string>
}>()

const chartsContainer = ref<HTMLElement | null>(null)

function computeSpeakerStats(topic: string, points: Point[]) {
  const topicPoints = points.filter((p) => p.topic === topic)
  const speakerChars = new Map<string, number>()

  topicPoints.forEach((p) => {
    const sp = (p.source || '未知').trim()
    const text = p.sentence || p.slot || ''
    const len = text.length
    speakerChars.set(sp, (speakerChars.get(sp) || 0) + len)
  })

  const total = [...speakerChars.values()].reduce((a, b) => a + b, 0)
  const stats: { speaker: string; chars: number; percent: number }[] = []

  speakerChars.forEach((chars, speaker) => {
    stats.push({
      speaker,
      chars,
      percent: total > 0 ? Math.round((chars / total) * 1000) / 10 : 0,
    })
  })

  stats.sort((a, b) => b.chars - a.chars)
  return { stats, total }
}

function renderCharts() {
  if (!chartsContainer.value) return

  const doRender = () => {
    const el = chartsContainer.value
    if (!el) return

    const w = el.clientWidth
    const h = el.clientHeight
    if (w === 0 || h === 0) {
      requestAnimationFrame(doRender)
      return
    }

    const container = d3.select(el)
    container.selectAll('*').remove()

    const topics = props.activeTopics
    if (!topics.length) return

    const svg = container.append('svg').attr('width', w).attr('height', h)

    // 饼图尺寸：最大 200px，根据主题数量自适应
    const maxSize = 200
    const chartSize = Math.min(maxSize, (w - 20) / topics.length, h - 20)
    if (chartSize <= 40) return
    const radius = (chartSize / 2) - 12
    const totalWidth = topics.length * chartSize
    const startX = Math.max(10, (w - totalWidth) / 2)

    topics.forEach((topic, ti) => {
      const { stats } = computeSpeakerStats(topic, props.allPoints)
      if (!stats.length) return

      const cx = startX + ti * chartSize + chartSize / 2
      const cy = h / 2

      const chartG = svg.append('g').attr('transform', `translate(${cx}, ${cy})`)

      const pie = d3
        .pie<{ speaker: string; chars: number; percent: number }>()
        .value((d) => d.chars)
        .sort(null)

      const arc = d3
        .arc<d3.PieArcDatum<{ speaker: string; chars: number; percent: number }>>()
        .innerRadius(radius * 0.45)
        .outerRadius(radius)

      const arcs = chartG.selectAll('path').data(pie(stats)).enter()

      arcs
        .append('path')
        .attr('d', arc)
        .attr('fill', (d) => props.speakerColorMap[d.data.speaker] || '#999')
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
        .attr('opacity', 0.85)
        .append('title')
        .text((d) => `${d.data.speaker}: ${d.data.percent}%`)

      chartG
        .append('text')
        .attr('y', -radius - 14)
        .attr('text-anchor', 'middle')
        .attr('fill', props.topicColorMap[topic] || '#333')
        .attr('font-size', 13)
        .attr('font-weight', '600')
        .text(topic)

      const legendG = chartG.append('g').attr('transform', `translate(${radius + 16}, ${-stats.length * 10})`)

      stats.forEach((s, i) => {
        const row = legendG.append('g').attr('transform', `translate(0, ${i * 20})`)

        row
          .append('circle')
          .attr('r', 5)
          .attr('fill', props.speakerColorMap[s.speaker] || '#999')

        row
          .append('text')
          .attr('x', 12)
          .attr('y', 4)
          .attr('fill', '#333')
          .attr('font-size', 11)
          .text(`${s.speaker}  ${s.percent}%`)
      })
    })
  }
  doRender()
}

watch(
  () => [props.activeTopics, props.allPoints],
  () => nextTick(renderCharts),
  { deep: true },
)

onMounted(() => nextTick(renderCharts))
</script>

<style scoped>
.dashboard-container {
  width: 100%;
  height: 100%;
  background: #fafafa;
  border-top: 2px solid #e0e0e0;
  display: flex;
  flex-direction: row;
}

.dashboard-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  user-select: none;
}

/* 左侧：饼图 */
.dashboard-left {
  flex: 6;
  min-width: 0;
  min-height: 0;
}

/* 右侧：预留面板 */
.dashboard-right {
  flex: 4;
  min-width: 0;
  border-left: 1px solid #e0e0e0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #bbb;
  user-select: none;
}

.placeholder-icon {
  font-size: 36px;
  opacity: 0.5;
}

.placeholder-text {
  font-size: 13px;
}
</style>

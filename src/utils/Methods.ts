import * as d3 from 'd3'

export function computeKDE1D(
  samples: number[],
  xs: number[],
  bandwidth: number,
): { x: number; value: number }[] {
  const n = samples.length
  if (n === 0) return xs.map((x) => ({ x, value: 0 }))

  const h = bandwidth
  const invH = 1 / h
  const values = xs.map((x) => ({ x, value: 0 }))

  // Epanechnikov: K(u)=0.75*(1-u^2) for |u|<=1 else 0
  for (const t of samples) {
    for (const v of values) {
      const u = (v.x - t) * invH
      v.value += Math.exp(-0.5 * u * u)
    }
  }

  // 归一化：1/(n*h)
  const normFactor = 1 / (n * h * Math.sqrt(2 * Math.PI))
  for (const v of values) v.value *= normFactor

  return values
}

export type SlotCluster = {
  topic: string
  clusterIndex: number
  startId: number
  endId: number
  ids: number[]
  length: number
}

export function clusterSlotIdsByTopic(
  slotIdsByTopic: Map<string, Set<number>>,
  gapTol: number = 1,
  minLen: number = 1,
): Record<string, SlotCluster[]> {
  const out: Record<string, SlotCluster[]> = {}

  for (const [topic, idSet] of slotIdsByTopic.entries()) {
    const ids = Array.from(idSet).sort((a, b) => a - b)
    const clusters: SlotCluster[] = []
    if (ids.length === 0) {
      out[topic] = clusters
      continue
    }

    let cur: number[] = [ids[0]]
    for (let i = 1; i < ids.length; i++) {
      const prev = ids[i - 1]
      const now = ids[i]
      if (now - prev <= gapTol) cur.push(now)
      else {
        if (cur.length >= minLen) {
          clusters.push({
            topic,
            clusterIndex: clusters.length,
            startId: cur[0],
            endId: cur[cur.length - 1],
            ids: cur.slice(),
            length: cur.length,
          })
        }
        cur = [now]
      }
    }

    if (cur.length >= minLen) {
      clusters.push({
        topic,
        clusterIndex: clusters.length,
        startId: cur[0],
        endId: cur[cur.length - 1],
        ids: cur.slice(),
        length: cur.length,
      })
    }

    out[topic] = clusters
  }

  return out
}

/** 避让布局：修改 points 内的 _y（原地更新） */
export function resolveY<T extends { _ty: number; _y: number }>(
  points: T[],
  yMin: number,
  yMax: number,
  minGap: number,
) {
  const ps = points.slice().sort((a, b) => a._ty - b._ty)

  let cur = yMin
  for (const d of ps) {
    cur = Math.max(d._ty, cur)
    d._y = cur
    cur += minGap
  }

  const overflow = ps[ps.length - 1]._y - yMax
  if (overflow > 0) {
    for (const d of ps) d._y -= overflow
  }

  for (let i = ps.length - 2; i >= 0; i--) {
    const maxAllowed = ps[i + 1]._y - minGap
    ps[i]._y = Math.min(ps[i]._y, maxAllowed)
  }

  const topOverflow = yMin - ps[0]._y
  if (topOverflow > 0) {
    for (const d of ps) d._y += topOverflow
  }
}

export function highlightTopicBands(activeTopic: string | null) {
  const bands = d3.selectAll<SVGPathElement, unknown>('path.topic-band')
  bands
    .interrupt()
    .transition()
    .duration(400)
    .ease(d3.easeCubicInOut)
    .attr('fill-opacity', function () {
      const t = d3.select(this).attr('data-topic')
      if (!activeTopic) return 0.6
      return t === activeTopic ? 0.6 : 0.2
    })
    .attr('transform', 'translate(0,0) scale(1,1)')
}



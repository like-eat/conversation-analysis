// ===== 4.2 选出要放大的“原始窗口”里的小胶囊 =====
    const Ymid = (Y1 + Y2) / 2
    const Lin = (Y2 - Y1) / LENS_SCALE // 被放大的原始窗口的高度
    const innerTop = Ymid - Lin / 2
    const innerBottom = Ymid + Lin / 2

    // 注意：这里用的是“全屏展开之后”的 s.y 来筛选
    const slotsInWindow = allSlots.filter((s) => s.y! >= innerTop && s.y! <= innerBottom)

    const n = slotsInWindow.length

    // ===== 4.3 把这些小胶囊重新铺满 [Y1, Y2] =====
    if (n > 0) {
      const lensHeight = Y2 - Y1
      const blockH = lensHeight / n // 每个胶囊占的“格子高度”
      const capsuleScale = 0.7 // 胶囊本身高度占格子的比例
      const capsuleH = blockH * capsuleScale

      slotsInWindow.forEach((s, i) => {
        // 中心位置均匀排布
        s.y = Y1 + blockH * (i + 0.5)

        // 半高（capsulePath 里 rh 是半高）
        s.rh = capsuleH / 2

        // 半宽可以稍微放大一点
        s.rw = (s.baseRw || s.rw || 0 || rx * 0.5) * LENS_SCALE
      })
    }

    // ===== 4.4 只画“放大后的那几颗小胶囊” =====
    layer
      .selectAll<SVGPathElement, SlotEx>('.slot')
      .data(slotsInWindow)
      .enter()
      .append('path')
      .attr('class', 'slot')
      .attr('d', (s) => capsulePath(s.x!, s.y!, s.rw!, s.rh!))
      .attr('fill', (s) => s.color)
      .attr('opacity', 0.95)
      .on('click', (event, s) => {
        event.stopPropagation()
        onSlotClick(s.id)
      })
export function createSeoTable(doc, rows = 3, cols = 3, header = false) {
  if (!Number.isInteger(rows) || rows < 1 || rows > 20 || !Number.isInteger(cols) || cols < 1 || cols > 10) throw Error('表格范围：1–20 行，1–10 列')
  const table = doc.createElement('table'); table.className = 'seo-table'
  const body = table.createTBody()
  for (let r = 0; r < rows; r++) {
    const row = (header && r === 0 ? table.createTHead() : body).insertRow()
    for (let c = 0; c < cols; c++) {
      const cell = doc.createElement(header && r === 0 ? 'th' : 'td')
      cell.innerHTML = '<br>'; row.append(cell)
    }
  }
  return table
}

export function editSeoTable(cell, action) {
  const table = cell?.closest('table'), row = cell?.closest('tr')
  if (!table || !row) return false
  if (action === 'deleteTable') { table.remove(); return true }
  // Merged cells need a grid model; preserve them rather than corrupting pasted tables.
  if ([...table.querySelectorAll('th,td')].some(node => node.colSpan > 1 || node.rowSpan > 1)) throw Error('含合并单元格的表格请先取消合并或删除整表')
  const rows = [...table.rows], index = [...row.cells].indexOf(cell)
  if (action === 'deleteRow') {
    row.remove(); if (!table.rows.length) table.remove()
  } else if (action === 'deleteColumn') {
    rows.forEach(item => item.cells[index]?.remove())
    if (!table.querySelector('th,td')) table.remove()
  } else if (action === 'rowAbove' || action === 'rowBelow') {
    if (rows.length >= 20) throw Error('最多 20 行')
    const next = row.cloneNode(true)
    for (const cell of next.cells) { cell.removeAttribute('id'); cell.innerHTML = '<br>' }
    row[action === 'rowAbove' ? 'before' : 'after'](next)
  } else if (action === 'columnLeft' || action === 'columnRight') {
    if (rows.some(item => item.cells.length >= 10)) throw Error('最多 10 列')
    rows.forEach(item => {
      const target = item.cells[index]
      if (!target) return
      const next = table.ownerDocument.createElement(target.tagName)
      next.innerHTML = '<br>'; target[action === 'columnLeft' ? 'before' : 'after'](next)
    })
  } else return false
  return true
}

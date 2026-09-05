import { platformHosts, validatePackage, sanitizeRichText } from './publisher/core.js'

export function createPublisherPackage(rows) {
  return validatePackage({ schema: 'seo-domestic-publisher-v1', items: rows.filter(row => row.status === 'manual_required' && platformHosts[row.platform_code]).map(row => ({
    publication_id: row.id, platform_code: row.platform_code, account: row.connection_name || row.platform_name,
    title: row.adapted_title || row.content_title, text: plainArticle(row.adapted_content || ''),
    html: sanitizeRichText(row.adapted_content || ''),
    editor_url: row.handoff_url, source_version: row.source_version,
  })) })
}

export function plainArticle(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('script,style,iframe,object,template').forEach(el => el.remove())
  doc.querySelectorAll('br').forEach(el => el.replaceWith('\n'))
  doc.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,blockquote,pre').forEach(el => el.append('\n'))
  return (doc.body.textContent || '').replace(/\n{3,}/g, '\n\n').trim()
}

// Small deterministic store-only ZIP; no new dependency or remote packaging service.
export function publisherZip(files) {
  const encode = value => new TextEncoder().encode(value.replace(/^\uFEFF/, ''))
  const crc = bytes => {
    let n = 0xffffffff
    for (const b of bytes) { n ^= b; for (let k=0;k<8;k++) n = (n >>> 1) ^ (n & 1 ? 0xedb88320 : 0) }
    return (n ^ 0xffffffff) >>> 0
  }
  const header = (size, fields) => {
    const data = new Uint8Array(size); const view = new DataView(data.buffer)
    for (const [offset, value, width] of fields) width === 4 ? view.setUint32(offset, value, true) : view.setUint16(offset, value, true)
    return data
  }
  const parts=[], directory=[]; let offset=0; let dirSize=0
  for (const [name, value] of Object.entries(files).sort(([a],[b]) => a.localeCompare(b))) {
    if (!/^[a-zA-Z0-9_.-]+$/.test(name)) throw new Error('扩展包文件名无效')
    const filename=encode(name), body=encode(value), hash=crc(body)
    const local=header(30,[[0,0x04034b50,4],[4,20,2],[6,0x800,2],[14,hash,4],[18,body.length,4],[22,body.length,4],[26,filename.length,2]])
    const central=header(46,[[0,0x02014b50,4],[4,20,2],[6,20,2],[8,0x800,2],[16,hash,4],[20,body.length,4],[24,body.length,4],[28,filename.length,2],[42,offset,4]])
    parts.push(local,filename,body); directory.push(central,filename)
    offset+=local.length+filename.length+body.length; dirSize+=central.length+filename.length
  }
  const count=Object.keys(files).length
  return new Blob([...parts,...directory,header(22,[[0,0x06054b50,4],[8,count,2],[10,count,2],[12,dirSize,4],[16,offset,4]])],{type:'application/zip'})
}

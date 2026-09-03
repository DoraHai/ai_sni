// Keep this allowlist aligned with sanitize_article_html on the SEO backend.
// DIV is emitted by contenteditable when Enter creates a paragraph.
const allowedTags = new Set(['P','DIV','H1','H2','H3','H4','H5','H6','A','IMG','UL','OL','LI','STRONG','B','EM','I','U','S','BLOCKQUOTE','PRE','CODE','BR','HR','TABLE','THEAD','TBODY','TR','TH','TD','FIGURE','FIGCAPTION'])
const blockedTags = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','FORM','INPUT','BUTTON','LINK','META'])
const allowedAttributes = new Set(['href','src','data-src','alt','title'])
const handoffHeading = '页面整改交接单（AI 辅助，人工编辑，勿直接发布）'

// Use before sending plain text to the HTML-capable content API. Escaping first
// keeps tag examples and literal entities intact through the backend sanitizer.
export function seoPlainTextHtml(value) {
  const text = String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return `<div>${text.replace(/\r\n?/g, '\n').replace(/\n/g, '<br>')}</div>`
}

function replaceTextNewlines(node, doc) {
  const lines = node.textContent.replace(/\r\n?/g, '\n').split('\n')
  const fragment = doc.createDocumentFragment()
  lines.forEach((line, index) => {
    if (index) fragment.append(doc.createElement('br'))
    fragment.append(doc.createTextNode(line))
  })
  node.replaceWith(fragment)
}

export function sanitizeSeoEditorHtml(value, doc = document) {
  const template = doc.createElement('template')
  const raw = String(value || '')
  // Match the API's _sanitize_content_html contract: values without '<' are
  // untouched plain text; HTML values have already had their entities encoded.
  // Parse HTML exactly once, never turn its serialized entities back into text.
  if (raw.includes('<')) template.innerHTML = raw
  else template.content.append(doc.createTextNode(raw))
  for (const node of [...template.content.querySelectorAll('*')]) {
    if (blockedTags.has(node.tagName)) {
      node.remove()
      continue
    }
    if (!allowedTags.has(node.tagName)) {
      node.replaceWith(...node.childNodes)
      continue
    }
    for (const attribute of [...node.attributes]) {
      if (!allowedAttributes.has(attribute.name.toLowerCase())) node.removeAttribute(attribute.name)
    }
    for (const name of ['href', 'src', 'data-src']) {
      const target = node.getAttribute(name)?.trim()
      if (target && !/^(https?:|\/|#)/i.test(target)) node.removeAttribute(name)
    }
  }

  // Legacy handoffs may be top-level text appended after rich content. Only
  // convert their text nodes, never tags or whitespace inside rich blocks.
  const plainText = !template.content.querySelector('*')
  let legacyHandoff = false
  for (const node of [...template.content.childNodes]) {
    if (node.nodeType !== 3) continue
    if (node.textContent.replace(/\r\n?/g, '\n').split('\n').includes(handoffHeading)) legacyHandoff = true
    if (plainText || (legacyHandoff && node.textContent.trim())) replaceTextNewlines(node, doc)
  }
  const html = template.innerHTML.trim()
  // An HTML serialization with entities but no tag would be mistaken for raw
  // text by the API on the next save. Keep the storage format unambiguous.
  return html && !html.includes('<') ? `<div>${html}</div>` : html
}

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '开始撰写正文…' },
  minHeight: { type: Number, default: 280 },
  maxHeight: { type: [Number, String], default: '' },
  disabled: { type: Boolean, default: false },
})

const contentStyle = computed(() => {
  const max = props.maxHeight
  const maxCss = max == null || max === ''
    ? undefined
    : typeof max === 'number'
      ? `${max}px`
      : String(max)
  return {
    minHeight: `${props.minHeight}px`,
    maxHeight: maxCss,
    overflowY: maxCss ? 'auto' : undefined,
  }
})

const emit = defineEmits(['update:modelValue'])
const editorRef = ref(null)
const focused = ref(false)
let lastEmitted = ''

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inlineMarkdown(value) {
  let text = escapeHtml(value)
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>')
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/~~([^~]+)~~/g, '<s>$1</s>')
  text = text.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  return text
}

function splitTableRow(line) {
  return String(line)
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function markdownToHtml(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let index = 0
  const isTableDivider = (line) => {
    const cells = splitTableRow(line)
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  }

  while (index < lines.length) {
    const raw = lines[index]
    const line = raw.trim()
    if (!line) {
      index += 1
      continue
    }

    if (line.includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headings = splitTableRow(line)
      const rows = []
      index += 2
      while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        rows.push(splitTableRow(lines[index]))
        index += 1
      }
      blocks.push(
        `<table><thead><tr>${headings.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead>` +
          `<tbody>${rows.map((row) => `<tr>${headings.map((_, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`,
      )
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    if (/^>\s?/.test(line)) {
      const quote = []
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quote.push(lines[index].trim().replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(`<blockquote>${inlineMarkdown(quote.join(' '))}</blockquote>`)
      continue
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/)
    const ordered = line.match(/^\d+\.\s+(.+)$/)
    if (unordered || ordered) {
      const orderedList = Boolean(ordered)
      const items = []
      const matcher = orderedList ? /^\d+\.\s+(.+)$/ : /^[-*+]\s+(.+)$/
      while (index < lines.length) {
        const match = lines[index].trim().match(matcher)
        if (!match) break
        items.push(match[1])
        index += 1
      }
      const tag = orderedList ? 'ol' : 'ul'
      blocks.push(`<${tag}>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</${tag}>`)
      continue
    }

    if (/^(-{3,}|\*{3,})$/.test(line)) {
      blocks.push('<hr>')
      index += 1
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,3})\s+/.test(lines[index].trim()) &&
      !/^>\s?/.test(lines[index].trim()) &&
      !/^[-*+]\s+/.test(lines[index].trim()) &&
      !/^\d+\.\s+/.test(lines[index].trim()) &&
      !(lines[index].includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1]))
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push(`<p>${inlineMarkdown(paragraph.join(' '))}</p>`)
  }

  return blocks.join('')
}

function nodeToMarkdown(node, depth = 0) {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || ''
  if (node.nodeType !== Node.ELEMENT_NODE) return ''

  const tag = node.tagName.toLowerCase()
  const children = () => Array.from(node.childNodes).map((child) => nodeToMarkdown(child, depth)).join('')
  if (tag === 'br') return '\n'
  if (tag === 'strong' || tag === 'b') return `**${children()}**`
  if (tag === 'em' || tag === 'i') return `*${children()}*`
  if (tag === 's' || tag === 'strike' || tag === 'del') return `~~${children()}~~`
  if (tag === 'code' && node.parentElement?.tagName.toLowerCase() !== 'pre') return `\`${children()}\``
  if (tag === 'a') {
    const href = node.getAttribute('href') || ''
    return href ? `[${children()}](${href})` : children()
  }
  if (/^h[1-3]$/.test(tag)) return `${'#'.repeat(Number(tag[1]))} ${children().trim()}\n\n`
  if (tag === 'p' || tag === 'div') return `${children().trim()}\n\n`
  if (tag === 'blockquote') return `${children().trim().split('\n').map((line) => `> ${line}`).join('\n')}\n\n`
  if (tag === 'hr') return '---\n\n'
  if (tag === 'ul' || tag === 'ol') {
    const ordered = tag === 'ol'
    return `${Array.from(node.children).map((item, itemIndex) => {
      const prefix = ordered ? `${itemIndex + 1}. ` : '- '
      return `${'  '.repeat(depth)}${prefix}${nodeToMarkdown(item, depth + 1).trim()}`
    }).join('\n')}\n\n`
  }
  if (tag === 'li') return children()
  if (tag === 'table') {
    const rows = Array.from(node.querySelectorAll('tr')).map((row) =>
      Array.from(row.querySelectorAll('th,td')).map((cell) => nodeToMarkdown(cell, depth).trim().replace(/\|/g, '\\|')),
    )
    if (!rows.length) return ''
    const width = Math.max(...rows.map((row) => row.length))
    const normalized = rows.map((row) => [...row, ...Array(width).fill('')].slice(0, width))
    return `| ${normalized[0].join(' | ')} |\n| ${Array(width).fill('---').join(' | ')} |\n${normalized.slice(1).map((row) => `| ${row.join(' | ')} |`).join('\n')}\n\n`
  }
  return children()
}

function htmlToMarkdown(html) {
  const container = document.createElement('div')
  container.innerHTML = html
  return Array.from(container.childNodes)
    .map((node) => nodeToMarkdown(node))
    .join('')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function syncEditor(markdown = props.modelValue) {
  if (!editorRef.value) return
  editorRef.value.innerHTML = markdownToHtml(markdown)
}

function emitValue() {
  if (!editorRef.value) return
  const markdown = htmlToMarkdown(editorRef.value.innerHTML)
  lastEmitted = markdown
  emit('update:modelValue', markdown)
}

function runCommand(command, value = null) {
  if (props.disabled) return
  editorRef.value?.focus()
  document.execCommand(command, false, value)
  emitValue()
}

function applyBlock(tag) {
  runCommand('formatBlock', tag)
}

function addLink() {
  const url = window.prompt('请输入链接地址（https://…）')
  if (!url) return
  runCommand('createLink', url)
}

function clearFormatting() {
  runCommand('removeFormat')
  applyBlock('p')
}

function onPaste(event) {
  const text = event.clipboardData?.getData('text/plain')
  if (!text) return
  event.preventDefault()
  document.execCommand('insertText', false, text)
  emitValue()
}

watch(
  () => props.modelValue,
  (value) => {
    if (value === lastEmitted) return
    if (focused.value) return
    nextTick(() => syncEditor(value))
  },
)

onMounted(() => syncEditor())
onBeforeUnmount(() => {
  if (focused.value) emitValue()
})
</script>

<template>
  <div class="rich-editor" :class="{ disabled, focused }">
    <div class="rich-toolbar" role="toolbar" aria-label="正文格式工具">
      <div class="tool-group">
        <button type="button" title="正文" @mousedown.prevent="applyBlock('p')">正文</button>
        <button type="button" title="二级标题" @mousedown.prevent="applyBlock('h2')">H2</button>
        <button type="button" title="三级标题" @mousedown.prevent="applyBlock('h3')">H3</button>
      </div>
      <span class="tool-separator" />
      <div class="tool-group">
        <button type="button" class="tool-strong" title="加粗" @mousedown.prevent="runCommand('bold')">B</button>
        <button type="button" class="tool-em" title="斜体" @mousedown.prevent="runCommand('italic')">I</button>
        <button type="button" class="tool-strike" title="删除线" @mousedown.prevent="runCommand('strikeThrough')">S</button>
        <button type="button" title="引用" @mousedown.prevent="applyBlock('blockquote')">❝</button>
      </div>
      <span class="tool-separator" />
      <div class="tool-group">
        <button type="button" title="无序列表" @mousedown.prevent="runCommand('insertUnorderedList')">• 列表</button>
        <button type="button" title="有序列表" @mousedown.prevent="runCommand('insertOrderedList')">1. 列表</button>
        <button type="button" title="插入链接" @mousedown.prevent="addLink">链接</button>
      </div>
      <span class="toolbar-spacer" />
      <button type="button" class="clear-button" title="清除格式" @mousedown.prevent="clearFormatting">清除格式</button>
    </div>
    <div
      ref="editorRef"
      class="rich-content"
      :class="{ empty: !modelValue }"
      :contenteditable="!disabled"
      :data-placeholder="placeholder"
      :style="contentStyle"
      role="textbox"
      aria-multiline="true"
      @focus="focused = true"
      @blur="focused = false; emitValue()"
      @input="emitValue"
      @paste="onPaste"
    />
    <div class="editor-status">
      <span>富文本编辑</span>
      <span>{{ modelValue.replace(/\s/g, '').length }} 字</span>
    </div>
  </div>
</template>

<style scoped>
.rich-editor {
  overflow: hidden;
  width: 100%;
  border: 1px solid #e2e6ee;
  border-radius: 12px;
  background: #fff;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}
.rich-editor.focused {
  border-color: #8b5cf6;
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.12);
}
.rich-editor.disabled { background: #f8fafc; opacity: 0.72; }
.rich-toolbar {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid #eef0f4;
  background: linear-gradient(180deg, #fbfcfe, #f7f8fb);
  flex-wrap: wrap;
}
.tool-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid #eef0f4;
}
.rich-toolbar button {
  height: 30px;
  min-width: 30px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #4b5565;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.rich-toolbar button:hover { color: #6d28d9; background: #f1eafe; }
.tool-separator { display: none; }
.toolbar-spacer { flex: 1; }
.tool-strong { font-weight: 800; }
.tool-em { font-family: Georgia, serif; font-style: italic; font-weight: 700; }
.tool-strike { text-decoration: line-through; }
.clear-button { color: #7c8494 !important; }
.rich-content {
  box-sizing: border-box;
  padding: 30px 38px 40px;
  outline: none;
  color: #1f2937;
  font-size: 15.5px;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.rich-content.empty::before {
  content: attr(data-placeholder);
  color: #a5adba;
  pointer-events: none;
}
.rich-content :deep(h1),
.rich-content :deep(h2),
.rich-content :deep(h3) {
  margin: 1.35em 0 0.65em;
  color: #111827;
  line-height: 1.35;
}
.rich-content :deep(h1:first-child),
.rich-content :deep(h2:first-child),
.rich-content :deep(h3:first-child) { margin-top: 0; }
.rich-content :deep(h1) { font-size: 1.65em; }
.rich-content :deep(h2) { font-size: 1.3em; }
.rich-content :deep(h3) { font-size: 1.12em; }
.rich-content :deep(p) { margin: 0 0 1em; }
.rich-content :deep(ul),
.rich-content :deep(ol) { margin: 0 0 1em; padding-left: 1.6em; }
.rich-content :deep(blockquote) {
  margin: 1em 0;
  padding: 10px 14px;
  border-left: 3px solid #8b5cf6;
  background: #faf8ff;
  color: #556070;
}
.rich-content :deep(a) { color: #6d28d9; text-decoration: underline; }
.rich-content :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #be123c;
}
.rich-content :deep(table) {
  width: 100%;
  margin: 16px 0;
  border-collapse: collapse;
  font-size: 14px;
}
.rich-content :deep(th),
.rich-content :deep(td) { padding: 9px 11px; border: 1px solid #dfe3eb; text-align: left; }
.rich-content :deep(th) { background: #f6f7fa; font-weight: 650; }
.editor-status {
  display: flex;
  justify-content: space-between;
  padding: 7px 12px;
  border-top: 1px solid #eef0f4;
  background: linear-gradient(180deg, #fcfcfd, #f8f9fb);
  color: #939bac;
  font-size: 11px;
  font-weight: 500;
}
@media (max-width: 720px) {
  .rich-content { padding: 20px 18px 26px; }
  .tool-separator { display: none; }
}
</style>

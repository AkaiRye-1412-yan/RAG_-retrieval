import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/common'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
  breaks: false,
  highlight(code, lang) {
    const language = lang && hljs.getLanguage(lang) ? lang : ''
    let body
    try {
      body = language
        ? hljs.highlight(code, { language, ignoreIllegals: true }).value
        : hljs.highlightAuto(code).value
    } catch {
      body = md.utils.escapeHtml(code)
    }
    const label = language || 'text'
    return (
      `<pre><span class="code-head"><span class="code-lang">${label}</span>` +
      `<button class="code-copy" type="button">复制</button></span><code>${body}</code></pre>`
    )
  },
})

const defaultLinkRender =
  md.renderer.rules.link_open ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }

md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkRender(tokens, idx, options, env, self)
}

export function renderMarkdown(text) {
  const html = md.render(text || '')
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}

// 事件委托：代码块复制
export function bindCopyButtons(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('.code-copy')
    if (!btn) return
    const pre = btn.closest('pre')
    const code = pre ? pre.querySelector('code') : null
    if (!code) return
    try {
      await navigator.clipboard.writeText(code.innerText)
      btn.textContent = '已复制'
      btn.classList.add('done')
      setTimeout(() => {
        btn.textContent = '复制'
        btn.classList.remove('done')
      }, 1500)
    } catch {
      /* 剪贴板不可用时静默 */
    }
  })
}

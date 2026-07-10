import { Fragment } from 'react'

/**
 * Renders the small markdown subset AURA's LLM output actually uses
 * (mirrors aura/app/services/jsm_client.py's markdown_to_adf, which converts
 * the same subset for Jira comments): **bold**, _italic_/*italic*, "---"
 * horizontal rules, and blank-line paragraph breaks.
 *
 * Without this, raw '**'/'*'/'_' characters showed up literally in chat
 * bubbles and suggestion panels instead of being rendered as formatting.
 */
export function MarkdownLite({ text }: { text: string }) {
  const blocks = splitBlocks(text)
  return (
    <>
      {blocks.map((block, i) =>
        block.type === 'rule' ? (
          <hr key={i} className="my-2 border-line" />
        ) : (
          <p key={i} className={i > 0 ? 'mt-2' : undefined}>
            {block.lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {renderInline(line)}
              </Fragment>
            ))}
          </p>
        ),
      )}
    </>
  )
}

type Block = { type: 'rule' } | { type: 'p'; lines: string[] }

function splitBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let current: string[] = []

  const flush = () => {
    if (current.length > 0) {
      blocks.push({ type: 'p', lines: current })
      current = []
    }
  }

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flush()
    } else if (/^-{3,}$/.test(line)) {
      flush()
      blocks.push({ type: 'rule' })
    } else {
      current.push(line)
    }
  }
  flush()

  return blocks.length > 0 ? blocks : [{ type: 'p', lines: [text] }]
}

// Pattern order matters: bold before italic so **x** isn't parsed as *·*x*·*.
const INLINE_PATTERN = /\*\*(.+?)\*\*|_(.+?)_|\*(.+?)\*/g

function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  let lastEnd = 0
  let key = 0

  for (const m of text.matchAll(INLINE_PATTERN)) {
    const start = m.index ?? 0
    if (start > lastEnd) nodes.push(text.slice(lastEnd, start))

    if (m[1] !== undefined) nodes.push(<strong key={key++}>{m[1]}</strong>)
    else if (m[2] !== undefined) nodes.push(<em key={key++}>{m[2]}</em>)
    else if (m[3] !== undefined) nodes.push(<em key={key++}>{m[3]}</em>)

    lastEnd = start + m[0].length
  }
  if (lastEnd < text.length) nodes.push(text.slice(lastEnd))

  return nodes
}

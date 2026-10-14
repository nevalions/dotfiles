import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Tone } from '../types'
import { SEPARATOR, segments } from './format'
import type { Limit } from './format'

const line = atom({ plugin: 'statusline', key: 'segments' } as const, [])

// Last readings; refetched on load, then pushed by session.measure.
let ctx = { window: 0, percent: 0 }
let limits: readonly Limit[] = []
let tick: Timer | undefined

const COLORS: Record<Tone, 'warning' | 'error' | undefined> = {
  normal: undefined, warning: 'warning', danger: 'error',
}

async function refresh($: EngineInterface) {
  const [cwd, model, now] = await Promise.all([$.session.cwd(), $.session.model(), $.clock.now()])
  const segs = segments({
    dir: cwd.split('/').filter(Boolean).pop() ?? cwd,
    model,
    window: ctx.window,
    percent: ctx.percent,
    limits,
    now: new Date(now),
  })
  await update($, line, () => segs)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    $.ui.status(undefined) // the pinned notice an earlier version drew
    const { context, rateLimits } = await $.session.usage()
    ctx = { window: context.window, percent: context.percent ?? 0 }
    limits = rateLimits
    tick?.cancel()
    tick = $.clock.every(60_000, () => void refresh($))
    await refresh($)
    return r
  })

  on('session.measure', async ($, e, next) => {
    ctx = { window: e.context.window, percent: e.context.percent ?? 0 }
    limits = e.rateLimits
    await refresh($)
    return next(e)
  })

  // The hint line under the prompt: the status on the left, coloured per
  // element, and the engine's own hint dim on the right.
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    const segs = await read($, line)
    if (segs.length === 0) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="row" justifyContent="space-between">
        <Text wrap="truncate-end">
          {segs.map((s, i) => (
            <Text>
              {i > 0 && <Text dimColor>{SEPARATOR}</Text>}
              <Text color={COLORS[s.tone]}>{s.text}</Text>
            </Text>
          ))}
        </Text>
        {e.props.hint !== '' && <Text dimColor wrap="truncate-end">{'  '}{e.props.hint}</Text>}
      </Box>
    )
  })
}

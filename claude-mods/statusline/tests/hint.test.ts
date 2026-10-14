import { expect, mock, test } from 'claude-code/testing'

const HINT = {
  component: 'PromptHint',
  props: { isDraft: false, isWorking: true, hint: 'esc to interrupt' },
} as const

test('draws the status coloured per element, the engine hint beside it', async ($, on) => {
  mock.clock(on, { now: Date.parse('2026-10-14T12:00:00-07:00') })
  on('session.cwd', () => ({ value: '/home/u/code/kube-lvl47' }))
  on('session.model', () => ({ value: 'Opus 5.5' }))
  on('session.measure', ($, e) => ({ changed: e.changed }))
  await $.session.measure({
    context: { window: 1_000_000, tokens: 559_000, percent: 55.9 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 95 }, { kind: 'seven_day', percentUsed: 12 }],
    changed: ['context', 'rateLimits'],
  })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'statusline', surface, ...HINT })
    // The innermost Text holding a segment: the one that carries its colour.
    const seg = async (text: RegExp) => (await ui.findAll({ type: 'Text', text })).at(-1)?.props ?? {}
    expect(await ui.find({ type: 'Text', text: 'kube-lvl47' })).toBeDefined()
    expect(await seg(/550k\/1000k/)).toEqual({ color: 'warning' })
    expect(await seg(/5h .* 95%/)).toEqual({ color: 'error' })
    expect(await seg(/7d .* 12%/)).toEqual({})
    expect(await ui.find({ type: 'Text', text: /esc to interrupt/ })).toBeDefined()
    await ui.unmount()
  }
})

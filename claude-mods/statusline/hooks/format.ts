// Pure formatting, ported from the old statusline-command.sh.

import type { Segment, Tone } from '../types'

export type Figures = {
  dir: string
  model: string
  window: number
  percent: number
  limits: readonly Limit[]
  now: Date
}

// A rate-limit window as $.session.usage() reports it.
export type Limit = { kind: string; percentUsed: number; resetsAt?: string }

// Context figures are always in k, as the script printed them.
const kTok = (n: number) => (n >= 1000 ? `${Math.floor(n / 1000)}k` : `${n}`)

const hm = (mins: number) => {
  const h = Math.floor(mins / 60), m = mins % 60
  return h > 0 ? `${h}h${m}m` : `${m}m`
}

const bar = (pct: number, width: number) => {
  const filled = Math.floor((Math.max(0, Math.min(100, pct)) * width) / 100)
  return '▓'.repeat(filled) + '░'.repeat(width - filled)
}

const tone = (pct: number, warning: number, danger: number): Tone =>
  pct >= danger ? 'danger' : pct >= warning ? 'warning' : 'normal'

// Hour and minute in America/Los_Angeles.
export const pacific = (now: Date): { h: number; m: number } => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(now)
  const get = (t: string) => Number(parts.find(p => p.type === t)?.value ?? 0)
  return { h: get('hour') % 24, m: get('minute') }
}

// Peak hours: 5:00–11:00 Pacific.
export const peak = (now: Date): Segment => {
  const { h, m } = pacific(now)
  const minsNow = h * 60 + m
  if (h >= 5 && h < 11) return { text: `PEAK ${hm(11 * 60 - minsNow)} left`, tone: 'warning' }
  const to = h >= 11 ? 24 * 60 - minsNow + 5 * 60 : 5 * 60 - minsNow
  return { text: `peak in ${hm(to)}`, tone: 'normal' }
}

const LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d' }

// "5h [▓▓░░░] 42% ↻2h10m": usage of one window and the time to its reset.
export const limit = (l: Limit, now: Date): Segment => {
  const label = LABELS[l.kind] ?? l.kind
  let reset = ''
  if (l.resetsAt) {
    const mins = Math.max(0, Math.round((Date.parse(l.resetsAt) - now.getTime()) / 60_000))
    reset = mins >= 24 * 60
      ? ` ↻${Math.floor(mins / 1440)}d${Math.floor((mins % 1440) / 60)}h`
      : ` ↻${hm(mins)}`
  }
  return {
    text: `${label} [${bar(l.percentUsed, 5)}] ${Math.round(l.percentUsed)}%${reset}`,
    tone: tone(l.percentUsed, 70, 90),
  }
}

export const segments = (f: Figures): Segment[] => {
  const pct = Math.max(0, Math.min(100, Math.floor(f.percent)))
  const used = Math.floor((f.window * pct) / 100)
  const out: Segment[] = [{ text: f.dir, tone: 'normal' }]
  if (f.model) out.push({ text: f.model, tone: 'normal' })
  // The script turned yellow at 500k and red at 750k of a 1M window.
  out.push({ text: `[${bar(pct, 10)}] ${kTok(used)}/${kTok(f.window)}`, tone: tone(pct, 50, 75) })
  for (const kind of ['five_hour', 'seven_day']) {
    const l = f.limits.find(x => x.kind === kind)
    if (l) out.push(limit(l, f.now))
  }
  out.push(peak(f.now))
  return out
}

export const SEPARATOR = ' | '

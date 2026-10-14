import { expect, test } from 'claude-code/testing'

import { SEPARATOR, limit, peak, segments } from '../hooks/format'

// 2026-10-14 is PDT (UTC-7).
const at = (pdt: string) => new Date(`2026-10-14T${pdt}:00-07:00`)

test('counts down inside and outside peak hours; peak itself warns', () => {
  expect(peak(at('06:30'))).toEqual({ text: 'PEAK 4h30m left', tone: 'warning' })
  expect(peak(at('10:45')).text).toBe('PEAK 15m left')
  expect(peak(at('11:00'))).toEqual({ text: 'peak in 18h0m', tone: 'normal' })
  expect(peak(at('04:20')).text).toBe('peak in 40m')
})

test('rate-limit window: bar, reset countdown, tone by usage', () => {
  expect(limit({ kind: 'five_hour', percentUsed: 0, resetsAt: '2026-10-14T12:40:00-07:00' }, at('12:00')))
    .toEqual({ text: '5h [░░░░░] 0% ↻40m', tone: 'normal' })
  expect(limit({ kind: 'seven_day', percentUsed: 72 }, at('12:00')).tone).toBe('warning')
  expect(limit({ kind: 'five_hour', percentUsed: 95 }, at('12:00')))
    .toEqual({ text: '5h [▓▓▓▓░] 95%', tone: 'danger' })
})

test('colours only the elements past their thresholds', () => {
  const segs = segments({
    dir: 'kube-lvl47', model: 'Opus 5.5', window: 1_000_000, percent: 55.9, now: at('12:00'),
    limits: [
      { kind: 'seven_day', percentUsed: 12, resetsAt: '2026-10-17T15:00:00-07:00' },
      { kind: 'five_hour', percentUsed: 42.5, resetsAt: '2026-10-14T14:10:00-07:00' },
    ],
  })
  expect(segs.map(s => s.text).join(SEPARATOR)).toBe(
    'kube-lvl47 | Opus 5.5 | [▓▓▓▓▓░░░░░] 550k/1000k | 5h [▓▓░░░] 43% ↻2h10m | 7d [░░░░░] 12% ↻3d3h | peak in 17h0m',
  )
  expect(segs.map(s => s.tone)).toEqual(['normal', 'normal', 'warning', 'normal', 'normal', 'normal'])
})

test('context turns danger at 75% and windows without a reading are left out', () => {
  const segs = segments({ dir: 'd', model: '', window: 200_000, percent: 80, limits: [], now: at('06:00') })
  expect(segs.map(s => s.text).join(SEPARATOR)).toBe('d | [▓▓▓▓▓▓▓▓░░] 160k/200k | PEAK 5h0m left')
  expect(segs[1]?.tone).toBe('danger')
})

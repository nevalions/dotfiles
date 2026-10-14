// How loudly one element of the line is drawn.
export type Tone = 'normal' | 'warning' | 'danger'

export type Segment = { text: string; tone: Tone }

declare module 'claude-code' {
  interface PluginState {
    statusline: { segments: Segment[] }
  }
}

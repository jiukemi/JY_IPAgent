/** Decode browser recording/upload to PCM wav so preview & save stay instant. */

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
}

function audioBufferToWav(buffer: AudioBuffer): Blob {
  const numChannels = 1
  const sampleRate = buffer.sampleRate
  const samples = buffer.length
  const bytesPerSample = 2
  const blockAlign = numChannels * bytesPerSample
  const dataSize = samples * blockAlign
  const ab = new ArrayBuffer(44 + dataSize)
  const view = new DataView(ab)

  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, numChannels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * blockAlign, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // Downmix to mono
  const ch0 = buffer.getChannelData(0)
  const ch1 = buffer.numberOfChannels > 1 ? buffer.getChannelData(1) : null
  let offset = 44
  for (let i = 0; i < samples; i++) {
    let s = ch0[i] || 0
    if (ch1) s = (s + (ch1[i] || 0)) / 2
    const v = Math.max(-1, Math.min(1, s))
    view.setInt16(offset, v < 0 ? v * 0x8000 : v * 0x7fff, true)
    offset += 2
  }
  return new Blob([ab], { type: 'audio/wav' })
}

/** Convert any playable audio Blob/File to a wav File (for record/upload preview + save). */
export async function normalizeAudioToWavFile(
  input: Blob,
  baseName = 'reference',
): Promise<File> {
  if (input.type === 'audio/wav' || /\.wav$/i.test((input as File).name || '')) {
    const name = (input as File).name || `${baseName}.wav`
    return input instanceof File ? input : new File([input], name, { type: 'audio/wav' })
  }
  const ctx = new AudioContext()
  try {
    const raw = await input.arrayBuffer()
    const decoded = await ctx.decodeAudioData(raw.slice(0))
    const wav = audioBufferToWav(decoded)
    const stem = baseName.replace(/\.[^.]+$/, '') || 'reference'
    return new File([wav], `${stem}.wav`, { type: 'audio/wav' })
  } finally {
    await ctx.close().catch(() => undefined)
  }
}

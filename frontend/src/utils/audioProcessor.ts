export interface AudioProcessingConfig {
  enableNoiseSuppression: boolean
  enableAutoGain: boolean
  enableHighPassFilter: boolean
  enableCompressor: boolean
  targetLevelDb: number
  highPassFrequency: number
  noiseSuppressionLevel: number
}

export const defaultAudioConfig: AudioProcessingConfig = {
  enableNoiseSuppression: true,
  enableAutoGain: true,
  enableHighPassFilter: true,
  enableCompressor: true,
  targetLevelDb: -16,
  highPassFrequency: 80,
  noiseSuppressionLevel: 0.6,
}

export class AudioProcessor {
  private audioContext: AudioContext | null = null
  private sourceNode: MediaStreamAudioSourceNode | null = null
  private gainNode: GainNode | null = null
  private analyserNode: AnalyserNode | null = null
  private highPassFilter: BiquadFilterNode | null = null
  private compressor: DynamicsCompressorNode | null = null
  private destination: MediaStreamAudioDestinationNode | null = null
  private stream: MediaStream | null = null
  private config: AudioProcessingConfig
  private processingInterval: number | null = null

  constructor(config?: Partial<AudioProcessingConfig>) {
    this.config = { ...defaultAudioConfig, ...config }
  }

  async init(stream: MediaStream): Promise<MediaStream> {
    this.stream = stream

    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    this.audioContext = new AudioContextClass({ sampleRate: 16000 })

    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume()
    }

    this.sourceNode = this.audioContext.createMediaStreamSource(stream)
    this.destination = this.audioContext.createMediaStreamDestination()

    let currentNode: AudioNode = this.sourceNode

    if (this.config.enableHighPassFilter) {
      this.highPassFilter = this.audioContext.createBiquadFilter()
      this.highPassFilter.type = 'highpass'
      this.highPassFilter.frequency.value = this.config.highPassFrequency
      this.highPassFilter.Q.value = 0.7
      currentNode.connect(this.highPassFilter)
      currentNode = this.highPassFilter
    }

    if (this.config.enableCompressor) {
      this.compressor = this.audioContext.createDynamicsCompressor()
      this.compressor.threshold.value = -24
      this.compressor.knee.value = 30
      this.compressor.ratio.value = 4
      this.compressor.attack.value = 0.003
      this.compressor.release.value = 0.25
      currentNode.connect(this.compressor)
      currentNode = this.compressor
    }

    this.gainNode = this.audioContext.createGain()
    this.gainNode.gain.value = 1.0
    currentNode.connect(this.gainNode)
    currentNode = this.gainNode

    this.analyserNode = this.audioContext.createAnalyser()
    this.analyserNode.fftSize = 2048
    this.analyserNode.smoothingTimeConstant = 0.8
    currentNode.connect(this.analyserNode)

    currentNode.connect(this.destination)

    if (this.config.enableAutoGain) {
      this.startAutoGainControl()
    }

    return this.destination.stream
  }

  private startAutoGainControl() {
    if (!this.analyserNode || !this.gainNode || this.processingInterval) return

    const dataArray = new Float32Array(this.analyserNode.fftSize)
    let smoothedLevel = -60

    this.processingInterval = window.setInterval(() => {
      if (!this.analyserNode || !this.gainNode) return

      this.analyserNode.getFloatTimeDomainData(dataArray)

      let sum = 0
      for (let i = 0; i < dataArray.length; i++) {
        sum += dataArray[i] * dataArray[i]
      }
      const rms = Math.sqrt(sum / dataArray.length)
      const currentDb = 20 * Math.log10(rms + 1e-10)

      smoothedLevel = smoothedLevel * 0.9 + currentDb * 0.1

      const levelDiff = this.config.targetLevelDb - smoothedLevel
      const gainDb = Math.max(-10, Math.min(20, levelDiff * 0.1))
      const gainLinear = Math.pow(10, gainDb / 20)

      const currentGain = this.gainNode.gain.value
      const newGain = currentGain * 0.9 + gainLinear * 0.1
      this.gainNode.gain.value = Math.max(0.1, Math.min(5.0, newGain))

      if (this.config.enableNoiseSuppression && smoothedLevel < -45) {
        this.gainNode.gain.value *= this.config.noiseSuppressionLevel
      }
    }, 50)
  }

  async processBlob(blob: Blob): Promise<Blob> {
    const arrayBuffer = await blob.arrayBuffer()
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    const offlineContext = new OfflineAudioContext(1, arrayBuffer.byteLength, 16000)

    const audioBuffer = await offlineContext.decodeAudioData(arrayBuffer.slice(0))
    const channelData = audioBuffer.getChannelData(0)

    const { data, rms } = this.normalizeVolume(channelData)
    const processedData = this.applySpectralSubtraction(data, rms)

    const newBuffer = offlineContext.createBuffer(1, processedData.length, 16000)
    newBuffer.copyToChannel(processedData, 0)

    const source = offlineContext.createBufferSource()
    source.buffer = newBuffer

    const highPass = offlineContext.createBiquadFilter()
    highPass.type = 'highpass'
    highPass.frequency.value = this.config.highPassFrequency

    const compressor = offlineContext.createDynamicsCompressor()
    compressor.threshold.value = -24
    compressor.knee.value = 30
    compressor.ratio.value = 4
    compressor.attack.value = 0.003
    compressor.release.value = 0.25

    const gainNode = offlineContext.createGain()
    gainNode.gain.value = 1.0

    source.connect(highPass)
    highPass.connect(compressor)
    compressor.connect(gainNode)
    gainNode.connect(offlineContext.destination)

    source.start()
    const renderedBuffer = await offlineContext.startRendering()

    return this.bufferToWebmBlob(renderedBuffer)
  }

  private normalizeVolume(data: Float32Array): { data: Float32Array; rms: number } {
    let sum = 0
    for (let i = 0; i < data.length; i++) {
      sum += data[i] * data[i]
    }
    const rms = Math.sqrt(sum / data.length)
    const targetRms = Math.pow(10, this.config.targetLevelDb / 20)

    const normalized = new Float32Array(data.length)
    if (rms > 0.001) {
      const scale = targetRms / rms
      const clampedScale = Math.min(scale, 3.0)
      for (let i = 0; i < data.length; i++) {
        normalized[i] = Math.max(-1, Math.min(1, data[i] * clampedScale))
      }
    } else {
      normalized.set(data)
    }

    return { data: normalized, rms }
  }

  private applySpectralSubtraction(data: Float32Array, signalRms: number): Float32Array {
    const result = new Float32Array(data.length)
    const windowSize = 512
    const hopSize = 256
    const noiseEstimateFrames = Math.min(10, Math.floor(data.length / hopSize) - 1)

    let noiseProfile = new Float32Array(windowSize).fill(0)
    for (let f = 0; f < noiseEstimateFrames; f++) {
      const start = f * hopSize
      for (let i = 0; i < windowSize && start + i < data.length; i++) {
        noiseProfile[i] += Math.abs(data[start + i]) / noiseEstimateFrames
      }
    }

    const noiseThreshold = signalRms * 0.3
    for (let i = 0; i < data.length; i++) {
      const windowIdx = i % windowSize
      const noiseLevel = noiseProfile[windowIdx] * this.config.noiseSuppressionLevel
      if (noiseLevel < noiseThreshold) {
        result[i] = data[i]
      } else {
        const signal = Math.abs(data[i]) - noiseLevel
        result[i] = Math.sign(data[i]) * Math.max(0, signal)
      }
    }

    return result
  }

  private bufferToWebmBlob(buffer: AudioBuffer): Blob {
    const length = buffer.length * 4 + 44
    const arrayBuffer = new ArrayBuffer(length)
    const view = new DataView(arrayBuffer)

    const writeString = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i))
      }
    }

    writeString(0, 'RIFF')
    view.setUint32(4, length - 8, true)
    writeString(8, 'WAVE')
    writeString(12, 'fmt ')
    view.setUint32(16, 16, true)
    view.setUint16(20, 3, true)
    view.setUint16(22, 1, true)
    view.setUint32(24, buffer.sampleRate, true)
    view.setUint32(28, buffer.sampleRate * 4, true)
    view.setUint16(32, 4, true)
    view.setUint16(34, 32, true)
    writeString(36, 'data')
    view.setUint32(40, buffer.length * 4, true)

    const channelData = buffer.getChannelData(0)
    let offset = 44
    for (let i = 0; i < buffer.length; i++, offset += 4) {
      view.setFloat32(offset, channelData[i], true)
    }

    return new Blob([arrayBuffer], { type: 'audio/wav' })
  }

  getVolumeLevel(): number {
    if (!this.analyserNode) return 0

    const dataArray = new Float32Array(this.analyserNode.fftSize)
    this.analyserNode.getFloatTimeDomainData(dataArray)

    let sum = 0
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i] * dataArray[i]
    }
    const rms = Math.sqrt(sum / dataArray.length)
    return Math.min(1, Math.max(0, rms * 10))
  }

  async close() {
    if (this.processingInterval) {
      clearInterval(this.processingInterval)
      this.processingInterval = null
    }

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop())
      this.stream = null
    }

    if (this.audioContext) {
      await this.audioContext.close()
      this.audioContext = null
    }

    this.sourceNode = null
    this.gainNode = null
    this.analyserNode = null
    this.highPassFilter = null
    this.compressor = null
    this.destination = null
  }
}

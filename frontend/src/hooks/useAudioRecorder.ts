import { useState, useRef, useCallback, useEffect } from 'react'
import { AudioProcessor, AudioProcessingConfig, defaultAudioConfig } from '../utils/audioProcessor'

export function useAudioRecorder(customConfig?: Partial<AudioProcessingConfig>) {
  const [isRecording, setIsRecording] = useState(false)
  const [duration, setDuration] = useState(0)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [processedBlob, setProcessedBlob] = useState<Blob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [volumeLevel, setVolumeLevel] = useState(0)
  const [isProcessing, setIsProcessing] = useState(false)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const rawStreamRef = useRef<MediaStream | null>(null)
  const processedStreamRef = useRef<MediaStream | null>(null)
  const audioProcessorRef = useRef<AudioProcessor | null>(null)
  const timerRef = useRef<number | null>(null)
  const volumeMonitorRef = useRef<number | null>(null)
  const configRef = useRef<AudioProcessingConfig>({ ...defaultAudioConfig, ...customConfig })

  const startRecording = useCallback(async () => {
    try {
      setError(null)
      setIsProcessing(true)

      const rawStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      rawStreamRef.current = rawStream

      const processor = new AudioProcessor(configRef.current)
      audioProcessorRef.current = processor
      const processedStream = await processor.init(rawStream)
      processedStreamRef.current = processedStream

      let mimeType = 'audio/webm'
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus'
      } else if (MediaRecorder.isTypeSupported('audio/webm;codecs=pcm')) {
        mimeType = 'audio/webm;codecs=pcm'
      }

      const mediaRecorder = new MediaRecorder(processedStream, {
        mimeType,
        audioBitsPerSecond: 128000,
      })

      chunksRef.current = []
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data)
        }
      }

      mediaRecorder.onstop = async () => {
        const rawBlob = new Blob(chunksRef.current, { type: mimeType })
        setAudioBlob(rawBlob)
        setAudioUrl(URL.createObjectURL(rawBlob))

        if (audioProcessorRef.current) {
          try {
            setIsProcessing(true)
            const processed = await audioProcessorRef.current.processBlob(rawBlob)
            setProcessedBlob(processed)
          } catch (e) {
            console.error('Audio post-processing failed:', e)
            setProcessedBlob(rawBlob)
          } finally {
            setIsProcessing(false)
          }
        } else {
          setProcessedBlob(rawBlob)
        }

        cleanupStreams()
        setIsProcessing(false)
      }

      mediaRecorderRef.current = mediaRecorder
      mediaRecorder.start()
      setIsRecording(true)
      setDuration(0)
      setIsProcessing(false)

      const startTime = Date.now()
      timerRef.current = window.setInterval(() => {
        setDuration(Math.floor((Date.now() - startTime) / 1000))
      }, 100)

      volumeMonitorRef.current = window.setInterval(() => {
        if (audioProcessorRef.current) {
          const level = audioProcessorRef.current.getVolumeLevel()
          setVolumeLevel(level)
        }
      }, 100)
    } catch (err) {
      setIsProcessing(false)
      setError('无法访问麦克风，请确保已授予麦克风权限并检查设备是否正常')
      console.error('Recording error:', err)
      cleanupStreams()
    }
  }, [])

  const cleanupStreams = useCallback(() => {
    if (volumeMonitorRef.current) {
      clearInterval(volumeMonitorRef.current)
      volumeMonitorRef.current = null
    }
    setVolumeLevel(0)

    if (rawStreamRef.current) {
      rawStreamRef.current.getTracks().forEach((track) => track.stop())
      rawStreamRef.current = null
    }
    if (processedStreamRef.current) {
      processedStreamRef.current.getTracks().forEach((track) => track.stop())
      processedStreamRef.current = null
    }
  }, [])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)

      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [isRecording])

  const resetRecording = useCallback(() => {
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
    }
    if (audioProcessorRef.current) {
      audioProcessorRef.current.close()
      audioProcessorRef.current = null
    }
    cleanupStreams()

    setAudioUrl(null)
    setAudioBlob(null)
    setProcessedBlob(null)
    setDuration(0)
    setError(null)
    setIsProcessing(false)
  }, [audioUrl, cleanupStreams])

  const getAudioBase64 = useCallback(async (): Promise<string | null> => {
    const blobToUse = processedBlob || audioBlob
    if (!blobToUse) return null

    return new Promise((resolve) => {
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64 = reader.result as string
        const base64Data = base64.split(',')[1]
        resolve(base64Data)
      }
      reader.readAsDataURL(blobToUse)
    })
  }, [processedBlob, audioBlob])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (volumeMonitorRef.current) clearInterval(volumeMonitorRef.current)
      if (audioProcessorRef.current) {
        audioProcessorRef.current.close()
      }
      cleanupStreams()
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl)
      }
    }
  }, [audioUrl, cleanupStreams])

  return {
    isRecording,
    duration,
    audioUrl,
    audioBlob,
    processedBlob,
    error,
    volumeLevel,
    isProcessing,
    startRecording,
    stopRecording,
    resetRecording,
    getAudioBase64,
  }
}

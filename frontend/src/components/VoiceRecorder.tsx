import { useAudioRecorder } from '../hooks/useAudioRecorder'
import { LoadingSpinner } from './LoadingSpinner'

interface VoiceRecorderProps {
  onRecordingComplete: (base64Audio: string) => void
  minDuration?: number
  maxDuration?: number
  label?: string
}

export function VoiceRecorder({
  onRecordingComplete,
  minDuration = 1,
  maxDuration = 5,
  label = '录制语音',
}: VoiceRecorderProps) {
  const {
    isRecording,
    duration,
    audioUrl,
    error,
    startRecording,
    stopRecording,
    resetRecording,
    getAudioBase64,
  } = useAudioRecorder()

  const handleStart = () => {
    resetRecording()
    startRecording()
  }

  const handleStop = () => {
    stopRecording()
  }

  const handleSubmit = async () => {
    const base64 = await getAudioBase64()
    if (base64) {
      onRecordingComplete(base64)
    }
  }

  const formatDuration = (sec: number) => {
    return `${sec.toFixed(1)}s`
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      <div className="flex flex-col items-center space-y-4 py-6">
        {isRecording && (
          <div className="flex items-end space-x-1 h-8">
            {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
              <div
                key={i}
                className="w-2 bg-primary-500 rounded-full wave-bar"
                style={{
                  animationDelay: `${i * 0.1}s`,
                }}
              />
            ))}
          </div>
        )}

        {!isRecording && !audioUrl && (
          <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          </div>
        )}

        {audioUrl && !isRecording && (
          <div className="w-full">
            <audio controls src={audioUrl} className="w-full h-10" />
          </div>
        )}

        <div className="text-lg font-mono text-slate-600">
          {formatDuration(duration)} / {maxDuration}s
        </div>
      </div>

      <div className="flex gap-3">
        {!isRecording ? (
          !audioUrl ? (
            <button onClick={handleStart} className="btn-primary flex-1 flex items-center justify-center gap-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
              {label}
            </button>
          ) : (
            <>
              <button onClick={resetRecording} className="btn-secondary flex-1">
                重新录制
              </button>
              <button
                onClick={handleSubmit}
                disabled={duration < minDuration}
                className="btn-primary flex-1"
              >
                确认
              </button>
            </>
          )
        ) : (
          <button
            onClick={handleStop}
            disabled={duration >= maxDuration ? false : duration < minDuration}
            className="btn-primary flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700"
          >
            {duration >= maxDuration ? (
              <LoadingSpinner size="sm" className="border-white/30 border-t-white" />
            ) : (
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            )}
            {duration >= maxDuration ? '处理中...' : '停止录制'}
          </button>
        )}
      </div>

      {duration < minDuration && audioUrl && (
        <p className="text-sm text-amber-600 text-center">
          录音太短，请至少录制 {minDuration} 秒
        </p>
      )}
    </div>
  )
}

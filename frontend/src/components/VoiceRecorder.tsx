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
    volumeLevel,
    isProcessing,
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

  const getVolumeColor = (level: number) => {
    if (level < 0.2) return 'bg-slate-200'
    if (level < 0.5) return 'bg-green-500'
    if (level < 0.8) return 'bg-yellow-500'
    return 'bg-red-500'
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
          <div className="w-full space-y-3">
            <div className="flex items-center justify-center gap-2 h-16">
              {[...Array(12)].map((_, i) => {
                const barHeight = Math.max(
                  4,
                  Math.min(48, volumeLevel * 50 + Math.sin(i + Date.now() / 100) * 5)
                )
                return (
                  <div
                    key={i}
                    className={`w-3 rounded-full transition-all duration-75 ${getVolumeColor(volumeLevel)}`}
                    style={{
                      height: `${barHeight}px`,
                      opacity: 0.5 + volumeLevel * 0.5,
                    }}
                  />
                )
              })}
            </div>

            <div className="flex items-center justify-center gap-2">
              <span className="inline-flex items-center">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                <span className="ml-2 text-sm text-slate-600">录音中</span>
              </span>
              <span className="text-xs text-slate-500">
                音量: {Math.round(volumeLevel * 100)}%
              </span>
            </div>
          </div>
        )}

        {isProcessing && !isRecording && (
          <div className="flex flex-col items-center gap-3 py-4">
            <LoadingSpinner size="lg" />
            <p className="text-sm text-slate-600">正在进行降噪和音量归一化处理...</p>
          </div>
        )}

        {!isRecording && !audioUrl && !isProcessing && (
          <div className="text-center space-y-3">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto">
              <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <p className="text-xs text-slate-500">支持 AI 降噪 + 音量自动归一化</p>
          </div>
        )}

        {audioUrl && !isRecording && !isProcessing && (
          <div className="w-full space-y-3">
            <div className="p-3 bg-green-50 border border-green-200 rounded-lg">
              <p className="text-xs text-green-700 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                音频预处理完成（降噪 + 音量归一化）
              </p>
            </div>
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
            <button
              onClick={handleStart}
              disabled={isProcessing}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
            >
              {isProcessing ? (
                <LoadingSpinner size="sm" className="border-white/30 border-t-white" />
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              )}
              {isProcessing ? '初始化中...' : label}
            </button>
          ) : (
            <>
              <button onClick={resetRecording} className="btn-secondary flex-1">
                重新录制
              </button>
              <button
                onClick={handleSubmit}
                disabled={duration < minDuration || isProcessing}
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

      <div className="p-3 bg-blue-50 rounded-lg">
        <h4 className="text-xs font-medium text-blue-800 mb-1">💡 录音建议</h4>
        <ul className="text-xs text-blue-700 space-y-0.5">
          <li>• 在安静环境下录制，避免背景噪音</li>
          <li>• 保持麦克风距离嘴部 10-20 厘米</li>
          <li>• 以正常语速清晰朗读，声音不要太小或太大</li>
          <li>• 系统会自动进行降噪和音量归一化处理</li>
        </ul>
      </div>
    </div>
  )
}

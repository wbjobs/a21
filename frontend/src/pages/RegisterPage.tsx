import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { webauthnApi, voiceApi } from '../services/api'
import { handleRegistration } from '../utils/webauthn'
import { useAuth } from '../contexts/AuthContext'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { VoiceRecorder } from '../components/VoiceRecorder'
import type { User } from '../types'

type Step = 'info' | 'webauthn' | 'voice' | 'done'

export default function RegisterPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [step, setStep] = useState<Step>('info')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [formData, setFormData] = useState({
    username: '',
    email: '',
    displayName: '',
  })
  const [deviceName, setDeviceName] = useState('')
  const [registeredUser, setRegisteredUser] = useState<User | null>(null)
  const [voiceEnrolled, setVoiceEnrolled] = useState(false)

  const handleInfoSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setStep('webauthn')
  }

  const handleWebAuthnRegister = async () => {
    setLoading(true)
    setError(null)
    try {
      const options = await webauthnApi.startRegistration(
        formData.username,
        formData.email,
        formData.displayName || undefined
      )

      const credential = await handleRegistration(options)

      const user = await webauthnApi.finishRegistration(
        credential,
        formData.username,
        deviceName || undefined
      )

      setRegisteredUser(user)
      setStep('voice')
    } catch (err: any) {
      console.error('WebAuthn registration failed:', err)
      setError(
        err?.response?.data?.detail ||
          '设备绑定失败，请确保您的设备支持WebAuthn（指纹/人脸识别）并已授权。'
      )
    } finally {
      setLoading(false)
    }
  }

  const handleVoiceEnroll = async (base64Audio: string) => {
    if (!registeredUser) return

    setLoading(true)
    setError(null)
    try {
      await voiceApi.enroll(base64Audio, '初始声纹样本')
      setVoiceEnrolled(true)
      setStep('done')
    } catch (err: any) {
      console.error('Voice enrollment failed:', err)
      setError(
        err?.response?.data?.detail ||
          '声纹录入失败，请确保录音清晰且至少持续1秒。'
      )
    } finally {
      setLoading(false)
    }
  }

  const handleSkipVoice = () => {
    setStep('done')
  }

  const handleFinish = async () => {
    if (registeredUser) {
      const profile = await fetch('/api/auth/me', {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
      }).catch(() => null)

      if (profile?.ok) {
        const userData = await profile.json()
        login(localStorage.getItem('access_token') || '', userData)
      }
      navigate('/dashboard')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 mb-2">创建账户</h1>
          <p className="text-slate-600">无需密码，使用生物识别和声纹进行认证</p>
        </div>

        <div className="card">
          <div className="flex justify-between mb-8">
            {[
              { key: 'info', label: '基本信息', num: 1 },
              { key: 'webauthn', label: '设备绑定', num: 2 },
              { key: 'voice', label: '声纹录入', num: 3 },
              { key: 'done', label: '完成', num: 4 },
            ].map((item, idx) => {
              const steps: Step[] = ['info', 'webauthn', 'voice', 'done']
              const currentIdx = steps.indexOf(step)
              const itemIdx = steps.indexOf(item.key as Step)
              const isActive = itemIdx <= currentIdx

              return (
                <div key={item.key} className="flex-1 flex flex-col items-center">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-primary-600 text-white'
                        : 'bg-slate-100 text-slate-400'
                    }`}
                  >
                    {item.num}
                  </div>
                  <span
                    className={`mt-2 text-xs ${
                      isActive ? 'text-slate-700' : 'text-slate-400'
                    }`}
                  >
                    {item.label}
                  </span>
                </div>
              )
            })}
          </div>

          {error && (
            <div className="mb-6 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
              {error}
            </div>
          )}

          {step === 'info' && (
            <form onSubmit={handleInfoSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  用户名
                </label>
                <input
                  type="text"
                  value={formData.username}
                  onChange={(e) =>
                    setFormData({ ...formData, username: e.target.value })
                  }
                  className="input-field"
                  placeholder="请输入用户名"
                  required
                  minLength={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  邮箱
                </label>
                <input
                  type="email"
                  value={formData.email}
                  onChange={(e) =>
                    setFormData({ ...formData, email: e.target.value })
                  }
                  className="input-field"
                  placeholder="your@email.com"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  显示名称（可选）
                </label>
                <input
                  type="text"
                  value={formData.displayName}
                  onChange={(e) =>
                    setFormData({ ...formData, displayName: e.target.value })
                  }
                  className="input-field"
                  placeholder="您的昵称"
                />
              </div>
              <button type="submit" className="btn-primary w-full">
                下一步
              </button>
            </form>
          )}

          {step === 'webauthn' && (
            <div className="space-y-6">
              <div className="text-center py-4">
                <div className="w-16 h-16 mx-auto bg-blue-50 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-slate-900 mb-2">
                  绑定您的设备
                </h3>
                <p className="text-slate-600 text-sm mb-4">
                  点击下方按钮，使用指纹、面容或设备密码进行身份验证
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  设备名称（可选）
                </label>
                <input
                  type="text"
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  className="input-field"
                  placeholder="例如：我的手机、工作电脑"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep('info')}
                  className="btn-secondary flex-1"
                >
                  返回
                </button>
                <button
                  onClick={handleWebAuthnRegister}
                  disabled={loading}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {loading && <LoadingSpinner size="sm" className="border-white/30 border-t-white" />}
                  {loading ? '验证中...' : '开始绑定'}
                </button>
              </div>
            </div>
          )}

          {step === 'voice' && (
            <div className="space-y-6">
              <div className="text-center py-4">
                <div className="w-16 h-16 mx-auto bg-purple-50 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-slate-900 mb-2">
                  录入您的声纹
                </h3>
                <p className="text-slate-600 text-sm">
                  录制一段约3秒的语音样本，用于后续的声纹验证登录
                </p>
              </div>
              {loading ? (
                <div className="flex justify-center py-8">
                  <LoadingSpinner size="lg" />
                </div>
              ) : (
                <VoiceRecorder
                  onRecordingComplete={handleVoiceEnroll}
                  minDuration={2}
                  maxDuration={5}
                  label="录制语音样本"
                />
              )}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setStep('webauthn')}
                  className="btn-secondary flex-1"
                >
                  返回
                </button>
                <button
                  onClick={handleSkipVoice}
                  disabled={loading}
                  className="btn-secondary flex-1"
                >
                  跳过此步
                </button>
              </div>
              {voiceEnrolled && (
                <div className="p-3 bg-green-50 border border-green-200 text-green-700 rounded-lg text-sm text-center">
                  声纹录入成功！
                </div>
              )}
            </div>
          )}

          {step === 'done' && (
            <div className="text-center space-y-6 py-4">
              <div className="w-20 h-20 mx-auto bg-green-50 rounded-full flex items-center justify-center">
                <svg className="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div>
                <h3 className="text-xl font-semibold text-slate-900 mb-2">
                  注册完成！
                </h3>
                <p className="text-slate-600">
                  欢迎使用，{registeredUser?.display_name || registeredUser?.username}
                </p>
              </div>
              <button onClick={handleFinish} className="btn-primary w-full">
                进入主页
              </button>
            </div>
          )}
        </div>

        <p className="text-center text-slate-600 mt-6">
          已有账户？{' '}
          <Link to="/login" className="text-primary-600 hover:text-primary-700 font-medium">
            立即登录
          </Link>
        </p>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authApi, voiceApi } from '../services/api'
import { handleAuthentication } from '../utils/webauthn'
import { useAuth } from '../contexts/AuthContext'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { VoiceRecorder } from '../components/VoiceRecorder'
import type { VoiceChallenge } from '../types'

type LoginMethod = 'webauthn' | 'voice'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [method, setMethod] = useState<LoginMethod>('webauthn')
  const [username, setUsername] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [voiceChallenge, setVoiceChallenge] = useState<VoiceChallenge | null>(null)
  const [verifyResult, setVerifyResult] = useState<{ success: boolean; similarity: number | null; message: string } | null>(null)

  useEffect(() => {
    if (method === 'voice') {
      fetchVoiceChallenge()
    } else {
      setVoiceChallenge(null)
      setVerifyResult(null)
    }
  }, [method])

  const fetchVoiceChallenge = async () => {
    try {
      const challenge = await voiceApi.getChallenge()
      setVoiceChallenge(challenge)
      setError(null)
      setVerifyResult(null)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '获取验证挑战失败')
    }
  }

  const handleWebAuthnLogin = async () => {
    setLoading(true)
    setError(null)
    try {
      const options = await authApi.startWebAuthnAuth(username || undefined)
      const credential = await handleAuthentication(options)
      const tokenResponse = await authApi.finishWebAuthnAuth(credential)

      login(tokenResponse.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      console.error('WebAuthn login failed:', err)
      setError(
        err?.response?.data?.detail ||
          'WebAuthn 登录失败，请确保已绑定设备或使用声纹登录。'
      )
    } finally {
      setLoading(false)
    }
  }

  const handleVoiceVerify = async (base64Audio: string) => {
    if (!voiceChallenge) return

    setLoading(true)
    setError(null)
    setVerifyResult(null)
    try {
      const result = await voiceApi.verify(voiceChallenge.session_id, base64Audio)
      setVerifyResult({
        success: result.success,
        similarity: result.similarity,
        message: result.message,
      })

      if (result.success && result.user) {
        const tokenRes = await voiceApi.verifyAndLogin(
          voiceChallenge.session_id,
          base64Audio
        )
        login(tokenRes.access_token, result.user)
        navigate('/dashboard')
      } else {
        setTimeout(() => {
          fetchVoiceChallenge()
        }, 3000)
      }
    } catch (err: any) {
      console.error('Voice verification failed:', err)
      setError(
        err?.response?.data?.detail ||
          '声纹验证失败，请重新尝试。'
      )
      setTimeout(() => {
        fetchVoiceChallenge()
      }, 2000)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 mb-2">欢迎回来</h1>
          <p className="text-slate-600">使用您喜欢的方式登录</p>
        </div>

        <div className="card">
          <div className="flex gap-2 mb-6 p-1 bg-slate-100 rounded-xl">
            <button
              onClick={() => setMethod('webauthn')}
              className={`flex-1 py-2.5 px-4 rounded-lg font-medium text-sm transition-all ${
                method === 'webauthn'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                </svg>
                设备生物识别
              </span>
            </button>
            <button
              onClick={() => setMethod('voice')}
              className={`flex-1 py-2.5 px-4 rounded-lg font-medium text-sm transition-all ${
                method === 'voice'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
                声纹验证
              </span>
            </button>
          </div>

          {error && (
            <div className="mb-6 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
              {error}
            </div>
          )}

          {method === 'webauthn' && (
            <div className="space-y-6">
              <div className="text-center py-4">
                <div className="w-16 h-16 mx-auto bg-blue-50 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                  </svg>
                </div>
                <p className="text-slate-600 text-sm">
                  使用指纹、面容或设备密码快速登录
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  用户名（可选，用于快速匹配设备）
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-field"
                  placeholder="输入您的用户名"
                />
              </div>
              <button
                onClick={handleWebAuthnLogin}
                disabled={loading}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {loading && <LoadingSpinner size="sm" className="border-white/30 border-t-white" />}
                {loading ? '验证中...' : '使用设备登录'}
              </button>
            </div>
          )}

          {method === 'voice' && (
            <div className="space-y-6">
              <div className="text-center py-4">
                <div className="w-16 h-16 mx-auto bg-purple-50 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                </div>
                <p className="text-slate-600 text-sm mb-3">
                  请清晰地读出以下动态数字
                </p>
                {voiceChallenge && (
                  <div className="inline-flex items-center gap-2 px-6 py-3 bg-slate-900 rounded-xl">
                    <span className="text-4xl font-mono font-bold tracking-widest text-white">
                      {voiceChallenge.challenge_digits}
                    </span>
                    <button
                      onClick={fetchVoiceChallenge}
                      className="ml-2 p-1.5 text-slate-400 hover:text-white transition-colors"
                      title="换一组数字"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>

              {verifyResult && (
                <div
                  className={`p-3 border rounded-lg text-sm text-center ${
                    verifyResult.success
                      ? 'bg-green-50 border-green-200 text-green-700'
                      : 'bg-amber-50 border-amber-200 text-amber-700'
                  }`}
                >
                  {verifyResult.message}
                  {verifyResult.similarity !== null && (
                    <span className="ml-2 font-mono">
                      (相似度: {(verifyResult.similarity * 100).toFixed(1)}%)
                    </span>
                  )}
                </div>
              )}

              {loading ? (
                <div className="flex justify-center py-8">
                  <LoadingSpinner size="lg" />
                </div>
              ) : (
                voiceChallenge && (
                  <VoiceRecorder
                    onRecordingComplete={handleVoiceVerify}
                    minDuration={2}
                    maxDuration={5}
                    label="读出上方数字"
                  />
                )
              )}
            </div>
          )}
        </div>

        <p className="text-center text-slate-600 mt-6">
          还没有账户？{' '}
          <Link to="/register" className="text-primary-600 hover:text-primary-700 font-medium">
            立即注册
          </Link>
        </p>
      </div>
    </div>
  )
}

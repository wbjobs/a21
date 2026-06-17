import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { webauthnApi, voiceApi } from '../services/api'
import { handleRegistration } from '../utils/webauthn'
import { useAuth } from '../contexts/AuthContext'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { VoiceRecorder } from '../components/VoiceRecorder'
import { Modal } from '../components/Modal'
import type { WebAuthnCredential, VoicePrint } from '../types'

export default function DashboardPage() {
  const navigate = useNavigate()
  const { user, logout, refreshProfile } = useAuth()
  const [credentials, setCredentials] = useState<WebAuthnCredential[]>([])
  const [voiceprints, setVoiceprints] = useState<VoicePrint[]>([])
  const [loading, setLoading] = useState(true)

  const [showAddDevice, setShowAddDevice] = useState(false)
  const [showAddVoice, setShowAddVoice] = useState(false)
  const [deviceName, setDeviceName] = useState('')
  const [processing, setProcessing] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      await refreshProfile()
      const [creds, vps] = await Promise.all([
        webauthnApi.listCredentials(),
        voiceApi.listVoiceprints(),
      ])
      setCredentials(creds as unknown as WebAuthnCredential[])
      setVoiceprints(vps as unknown as VoicePrint[])
    } catch (err) {
      console.error('Failed to load data:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleAddDevice = async () => {
    if (!user) return
    setProcessing(true)
    setMessage(null)
    try {
      const options = await webauthnApi.startRegistration(
        user.username,
        user.email,
        user.display_name || undefined
      )
      const credential = await handleRegistration(options)
      await webauthnApi.finishRegistration(credential, user.username, deviceName || undefined)
      setShowAddDevice(false)
      setDeviceName('')
      setMessage({ type: 'success', text: '设备绑定成功！' })
      loadData()
      setTimeout(() => setMessage(null), 3000)
    } catch (err: any) {
      console.error('Add device failed:', err)
      setMessage({
        type: 'error',
        text: err?.response?.data?.detail || '设备绑定失败',
      })
    } finally {
      setProcessing(false)
    }
  }

  const handleAddVoice = async (base64Audio: string) => {
    setProcessing(true)
    setMessage(null)
    try {
      await voiceApi.enroll(base64Audio, `样本 ${voiceprints.length + 1}`)
      setShowAddVoice(false)
      setMessage({ type: 'success', text: '声纹录入成功！' })
      loadData()
      setTimeout(() => setMessage(null), 3000)
    } catch (err: any) {
      console.error('Add voiceprint failed:', err)
      setMessage({
        type: 'error',
        text: err?.response?.data?.detail || '声纹录入失败',
      })
    } finally {
      setProcessing(false)
    }
  }

  const handleDeleteCredential = async (id: number) => {
    if (!confirm('确定要删除此设备吗？')) return
    try {
      await webauthnApi.deleteCredential(id)
      setMessage({ type: 'success', text: '设备已删除' })
      loadData()
      setTimeout(() => setMessage(null), 3000)
    } catch (err: any) {
      setMessage({
        type: 'error',
        text: err?.response?.data?.detail || '删除失败',
      })
    }
  }

  const handleDeleteVoiceprint = async (id: number) => {
    if (!confirm('确定要删除此声纹吗？')) return
    try {
      await voiceApi.deleteVoiceprint(id)
      setMessage({ type: 'success', text: '声纹已删除' })
      loadData()
      setTimeout(() => setMessage(null), 3000)
    } catch (err: any) {
      setMessage({
        type: 'error',
        text: err?.response?.data?.detail || '删除失败',
      })
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-100">
        <div className="max-w-5xl mx-auto px-4 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-primary-700 rounded-xl flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <span className="font-semibold text-lg text-slate-900">VoiceAuth</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-600">
              {user?.display_name || user?.username}
            </span>
            <button
              onClick={handleLogout}
              className="text-sm text-slate-500 hover:text-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              退出登录
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {message && (
          <div
            className={`mb-6 p-4 rounded-xl border ${
              message.type === 'success'
                ? 'bg-green-50 border-green-200 text-green-700'
                : 'bg-red-50 border-red-200 text-red-700'
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-900 mb-1">账户管理</h1>
          <p className="text-slate-600">管理您的认证设备和声纹</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="card">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center">
                <svg className="w-6 h-6 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                </svg>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-900">{credentials.length}</div>
                <div className="text-sm text-slate-500">已绑定设备</div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-purple-50 rounded-xl flex items-center justify-center">
                <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-900">{voiceprints.length}</div>
                <div className="text-sm text-slate-500">声纹样本</div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-green-50 rounded-xl flex items-center justify-center">
                <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-900">
                  {credentials.length > 0 && voiceprints.length > 0 ? '双重' : credentials.length > 0 || voiceprints.length > 0 ? '单一' : '无'}
                </div>
                <div className="text-sm text-slate-500">认证方式</div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="card">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-lg font-semibold text-slate-900">绑定的设备</h2>
              <button
                onClick={() => setShowAddDevice(true)}
                className="btn-secondary text-sm py-2 px-4"
              >
                + 添加设备
              </button>
            </div>

            {credentials.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                </svg>
                <p>暂无绑定设备</p>
              </div>
            ) : (
              <div className="space-y-3">
                {credentials.map((cred) => (
                  <div
                    key={cred.id}
                    className="flex items-center justify-between p-4 bg-slate-50 rounded-xl"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center shadow-sm">
                        <svg className="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
                        </svg>
                      </div>
                      <div>
                        <div className="font-medium text-slate-900">
                          {cred.device_name || '未命名设备'}
                        </div>
                        <div className="text-xs text-slate-500">
                          绑定于 {formatDate(cred.created_at)}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteCredential(cred.id)}
                      className="text-slate-400 hover:text-red-600 transition-colors p-2"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-lg font-semibold text-slate-900">声纹样本</h2>
              <button
                onClick={() => setShowAddVoice(true)}
                className="btn-secondary text-sm py-2 px-4"
              >
                + 录入声纹
              </button>
            </div>

            {voiceprints.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
                <p>暂无声纹样本</p>
              </div>
            ) : (
              <div className="space-y-3">
                {voiceprints.map((vp) => (
                  <div
                    key={vp.id}
                    className="flex items-center justify-between p-4 bg-slate-50 rounded-xl"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center shadow-sm">
                        <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                        </svg>
                      </div>
                      <div>
                        <div className="font-medium text-slate-900">
                          {vp.sample_name || `样本 ${vp.id}`}
                        </div>
                        <div className="text-xs text-slate-500">
                          录入于 {formatDate(vp.created_at)}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteVoiceprint(vp.id)}
                      className="text-slate-400 hover:text-red-600 transition-colors p-2"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      <Modal
        isOpen={showAddDevice}
        onClose={() => setShowAddDevice(false)}
        title="绑定新设备"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            点击下方按钮，在新设备上使用指纹、面容或设备密码完成绑定。
          </p>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">
              设备名称（可选）
            </label>
            <input
              type="text"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              className="input-field"
              placeholder="例如：新手机、工作笔记本"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={() => setShowAddDevice(false)}
              className="btn-secondary flex-1"
            >
              取消
            </button>
            <button
              onClick={handleAddDevice}
              disabled={processing}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
            >
              {processing && <LoadingSpinner size="sm" className="border-white/30 border-t-white" />}
              {processing ? '绑定中...' : '开始绑定'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showAddVoice}
        onClose={() => setShowAddVoice(false)}
        title="录入新声纹"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            录制一段约3秒的语音，建议在安静环境下清晰朗读任意内容。
          </p>
          {processing ? (
            <div className="flex justify-center py-6">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <VoiceRecorder
              onRecordingComplete={handleAddVoice}
              minDuration={2}
              maxDuration={5}
              label="录制语音"
            />
          )}
          <button
            onClick={() => setShowAddVoice(false)}
            disabled={processing}
            className="btn-secondary w-full"
          >
            取消
          </button>
        </div>
      </Modal>
    </div>
  )
}

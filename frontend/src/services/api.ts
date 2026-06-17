import axios from 'axios'
import type {
  User,
  UserProfile,
  TokenResponse,
  RegistrationOptions,
  AuthenticationOptions,
  VoiceChallenge,
  VoiceVerifyResponse,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export const authApi = {
  getProfile: () => api.get<UserProfile>('/auth/me').then((r) => r.data),

  startWebAuthnAuth: (username?: string) =>
    api
      .post<AuthenticationOptions>('/auth/webauthn/start', null, {
        params: username ? { username } : undefined,
      })
      .then((r) => r.data),

  finishWebAuthnAuth: (credential: Record<string, unknown>) =>
    api.post<TokenResponse>('/auth/webauthn/finish', { credential }).then((r) => r.data),
}

export const webauthnApi = {
  startRegistration: (username: string, email: string, display_name?: string) =>
    api
      .post<RegistrationOptions>('/webauthn/register/start', {
        username,
        email,
        display_name,
      })
      .then((r) => r.data),

  finishRegistration: (
    credential: Record<string, unknown>,
    username: string,
    device_name?: string
  ) =>
    api
      .post<User>('/webauthn/register/finish', {
        credential,
        username,
        device_name,
      })
      .then((r) => r.data),

  listCredentials: () =>
    api.get<Array<{ id: number; device_name: string | null; transports: string | null; created_at: string }>>(
      '/webauthn/credentials'
    ).then((r) => r.data),

  deleteCredential: (id: number) =>
    api.delete(`/webauthn/credentials/${id}`).then((r) => r.data),
}

export const voiceApi = {
  enroll: (audioData: string, sample_name?: string) => {
    const formData = new FormData()
    formData.append('audio_data', audioData)
    if (sample_name) {
      formData.append('sample_name', sample_name)
    }
    return api
      .post<{ success: boolean; voiceprint_id: number; message: string }>(
        '/voice/enroll',
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
        }
      )
      .then((r) => r.data)
  },

  getChallenge: () =>
    api.get<VoiceChallenge>('/voice/challenge').then((r) => r.data),

  verify: (session_id: string, audio_data: string) =>
    api
      .post<VoiceVerifyResponse>('/voice/verify', { session_id, audio_data })
      .then((r) => r.data),

  verifyAndLogin: (session_id: string, audio_data: string) =>
    api
      .post<TokenResponse>('/voice/verify-login', { session_id, audio_data })
      .then((r) => r.data),

  listVoiceprints: () =>
    api
      .get<Array<{ id: number; sample_name: string | null; created_at: string }>>(
        '/voice/voiceprints'
      )
      .then((r) => r.data),

  deleteVoiceprint: (id: number) =>
    api.delete(`/voice/voiceprints/${id}`).then((r) => r.data),
}

export default api

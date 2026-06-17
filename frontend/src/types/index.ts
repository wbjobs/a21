export interface User {
  id: number
  username: string
  email: string
  display_name: string | null
  created_at: string
  is_active: boolean
}

export interface WebAuthnCredential {
  id: number
  device_name: string | null
  transports: string | null
  created_at: string
}

export interface VoicePrint {
  id: number
  sample_name: string | null
  created_at: string
}

export interface UserProfile extends User {
  credentials: WebAuthnCredential[]
  voiceprints: VoicePrint[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegistrationOptions {
  challenge: string
  user_id: string
  rp_id: string
  rp_name: string
  user_name: string
  user_display_name: string
  pub_key_cred_params: Array<{ type: string; alg: number }>
  timeout: number
  attestation: string
  authenticator_selection: Record<string, unknown>
  exclude_credentials: Array<{ id: string; type: string }>
}

export interface AuthenticationOptions {
  challenge: string
  rp_id: string
  timeout: number
  user_verification: string
  allow_credentials: Array<{ id: string; type: string }>
}

export interface VoiceChallenge {
  challenge_digits: string
  session_id: string
}

export interface VoiceVerifyResponse {
  success: boolean
  user: User | null
  similarity: number | null
  message: string
}

export interface RecordingState {
  isRecording: boolean
  duration: number
  audioUrl: string | null
}

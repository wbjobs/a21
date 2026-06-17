import {
  startRegistration as webauthnStartRegistration,
  startAuthentication as webauthnStartAuthentication,
} from '@simplewebauthn/browser'
import type {
  RegistrationOptions,
  AuthenticationOptions,
} from '../types'

function base64UrlToArrayBuffer(base64url: string): Uint8Array {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  const base64 = btoa(binary)
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export async function handleRegistration(options: RegistrationOptions) {
  const publicKeyOptions = {
    challenge: base64UrlToArrayBuffer(options.challenge),
    rp: {
      id: options.rp_id,
      name: options.rp_name,
    },
    user: {
      id: base64UrlToArrayBuffer(options.user_id),
      name: options.user_name,
      displayName: options.user_display_name,
    },
    pubKeyCredParams: options.pub_key_cred_params,
    timeout: options.timeout,
    attestation: options.attestation,
    excludeCredentials: options.exclude_credentials.map((cred) => ({
      id: base64UrlToArrayBuffer(cred.id),
      type: cred.type as PublicKeyCredentialType,
    })),
    authenticatorSelection: {
      requireResidentKey: options.authenticator_selection?.require_resident_key as boolean,
      userVerification: (options.authenticator_selection?.user_verification as UserVerificationRequirement) || 'preferred',
    },
  }

  try {
    const credential = await webauthnStartRegistration(publicKeyOptions as any)
    return credential
  } catch (error) {
    console.error('WebAuthn registration error:', error)
    throw error
  }
}

export async function handleAuthentication(options: AuthenticationOptions) {
  const publicKeyOptions = {
    challenge: base64UrlToArrayBuffer(options.challenge),
    rpId: options.rp_id,
    timeout: options.timeout,
    userVerification: options.user_verification as UserVerificationRequirement,
    allowCredentials: options.allow_credentials.map((cred) => ({
      id: base64UrlToArrayBuffer(cred.id),
      type: cred.type as PublicKeyCredentialType,
    })),
  }

  try {
    const credential = await webauthnStartAuthentication(publicKeyOptions as any)
    return credential
  } catch (error) {
    console.error('WebAuthn authentication error:', error)
    throw error
  }
}

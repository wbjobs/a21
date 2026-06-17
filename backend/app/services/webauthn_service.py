import json
import base64
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
    AuthenticationCredential,
    UserVerificationRequirement,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from app.core.config import settings
from typing import Optional, List, Tuple


class WebAuthnService:
    RP_ID = settings.webauthn_rp_id
    RP_NAME = settings.webauthn_rp_name
    ORIGIN = settings.webauthn_origin

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

    @staticmethod
    def _b64decode(data: str) -> bytes:
        padding = '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    @classmethod
    def start_registration(cls, user_id: str, username: str, display_name: str,
                           existing_credential_ids: Optional[List[str]] = None):
        exclude_credentials = []
        if existing_credential_ids:
            for cid in existing_credential_ids:
                try:
                    exclude_credentials.append(PublicKeyCredentialDescriptor(
                        id=cls._b64decode(cid),
                    ))
                except Exception:
                    pass

        options = generate_registration_options(
            rp_id=cls.RP_ID,
            rp_name=cls.RP_NAME,
            user_id=user_id.encode(),
            user_name=username,
            user_display_name=display_name,
            attestation="none",
            exclude_credentials=exclude_credentials,
            supported_pub_key_algs=[
                COSEAlgorithmIdentifier.ECDSA_SHA_256,
                COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
                COSEAlgorithmIdentifier.RSA_PSS_SHA_256,
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        return {
            "challenge": cls._b64encode(options.challenge),
            "user_id": cls._b64encode(options.user.id),
            "rp_id": options.rp.id,
            "rp_name": options.rp.name,
            "user_name": options.user.name,
            "user_display_name": options.user.display_name,
            "pub_key_cred_params": [
                {"type": p.type, "alg": p.alg.value} for p in options.pub_key_cred_params
            ],
            "timeout": options.timeout,
            "attestation": options.attestation,
            "authenticator_selection": {
                "require_resident_key": getattr(options.authenticator_selection, "require_resident_key", False),
                "user_verification": getattr(options.authenticator_selection, "user_verification", "preferred"),
            } if options.authenticator_selection else {},
            "exclude_credentials": [
                {"id": cls._b64encode(c.id), "type": c.type}
                for c in options.exclude_credentials
            ],
        }, cls._b64encode(options.challenge)

    @classmethod
    def finish_registration(cls, credential_dict: dict, challenge: str, origin: Optional[str] = None):
        try:
            credential = RegistrationCredential.parse_obj(credential_dict)
            challenge_bytes = cls._b64decode(challenge)

            verification = verify_registration_response(
                credential=credential,
                expected_challenge=challenge_bytes,
                expected_rp_id=cls.RP_ID,
                expected_origin=origin or cls.ORIGIN,
                require_user_verification=True,
            )

            return {
                "credential_id": cls._b64encode(verification.credential_id),
                "public_key": cls._b64encode(verification.credential_public_key),
                "sign_count": verification.sign_count,
                "transports": credential.response.transports if hasattr(credential.response, 'transports') else None,
            }
        except Exception as e:
            print(f"WebAuthn registration verification failed: {e}")
            return None

    @classmethod
    def start_authentication(cls, credential_ids: Optional[List[str]] = None):
        allow_credentials = []
        if credential_ids:
            for cid in credential_ids:
                try:
                    allow_credentials.append(PublicKeyCredentialDescriptor(
                        id=cls._b64decode(cid),
                    ))
                except Exception:
                    pass

        options = generate_authentication_options(
            rp_id=cls.RP_ID,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        return {
            "challenge": cls._b64encode(options.challenge),
            "rp_id": options.rp_id,
            "timeout": options.timeout,
            "user_verification": options.user_verification,
            "allow_credentials": [
                {"id": cls._b64encode(c.id), "type": c.type}
                for c in options.allow_credentials
            ],
        }, cls._b64encode(options.challenge)

    @classmethod
    def finish_authentication(cls, credential_dict: dict, challenge: str,
                              public_key: str, stored_sign_count: int,
                              origin: Optional[str] = None):
        try:
            credential = AuthenticationCredential.parse_obj(credential_dict)
            challenge_bytes = cls._b64decode(challenge)
            public_key_bytes = cls._b64decode(public_key)

            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge_bytes,
                expected_rp_id=cls.RP_ID,
                expected_origin=origin or cls.ORIGIN,
                credential_public_key=public_key_bytes,
                credential_current_sign_count=stored_sign_count,
                require_user_verification=True,
            )

            return {
                "credential_id": cls._b64encode(verification.credential_id),
                "new_sign_count": verification.new_sign_count,
            }
        except Exception as e:
            print(f"WebAuthn authentication verification failed: {e}")
            return None

import { generate } from 'otplib'

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

// deploy/keycloak/bootstrap.sh seeds each demo user's OTP credential with a
// fixed RAW secret string (dev/test only, guarded by APP_ENV there) and
// prints this same base32 encoding of it for a real authenticator app --
// otplib's functional API takes a base32 secret (matching
// generateSecret()'s own output format), so this mirrors that conversion
// here rather than duplicating the raw strings in two encodings.
export function base32Encode(raw: string): string {
  const bytes = Buffer.from(raw, 'utf-8')
  let bits = ''
  for (const byte of bytes) bits += byte.toString(2).padStart(8, '0')
  while (bits.length % 5 !== 0) bits += '0'
  let out = ''
  for (let i = 0; i < bits.length; i += 5) {
    out += BASE32_ALPHABET[parseInt(bits.slice(i, i + 5), 2)]
  }
  return out
}

// deploy/keycloak/bootstrap.sh's seed_totp() -- same raw strings, same
// order. Keep in sync if either changes.
export const DEMO_TOTP_SECRETS: Record<string, string> = {
  estimator1: 'installtec-dev-estimator1-totp01',
  lead1: 'installtec-dev-lead1-totp01-secret',
  procurement1: 'installtec-dev-procurement1-totp1',
  bd1: 'installtec-dev-bd1-totp-secret1',
  md1: 'installtec-dev-md1-totp-secret01',
  admin1: 'installtec-dev-admin1-totp-secret1',
}

// realm-installtec.json's otpPolicy is HmacSHA1/6 digits/30s step, which are
// otplib's own defaults -- no extra options needed.
export async function generateTotp(rawSecret: string): Promise<string> {
  return generate({ secret: base32Encode(rawSecret) })
}

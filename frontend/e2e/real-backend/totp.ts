import { createHmac } from 'node:crypto'

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

function base32Decode(input: string): Buffer {
  const clean = input.toUpperCase().replace(/[^A-Z2-7]/g, '')
  let bits = ''
  for (const char of clean) {
    const value = BASE32_ALPHABET.indexOf(char)
    if (value === -1) throw new Error(`Invalid base32 character in TOTP secret: ${char}`)
    bits += value.toString(2).padStart(5, '0')
  }
  const bytes: number[] = []
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2))
  }
  return Buffer.from(bytes)
}

// RFC 6238 TOTP (HMAC-SHA1, 6 digits, 30s step) -- matches
// deploy/keycloak/realm-installtec.json's otpPolicy for this dev realm
// import, not a general-purpose implementation. Used to complete a real
// Keycloak TOTP enrolment/step-up in e2e/real-backend specs without a new
// dependency (see enrollTotp/completeMfaStepUp in helpers.ts).
export function generateTotp(base32Secret: string, atMs: number = Date.now(), digits = 6, stepSeconds = 30): string {
  const key = base32Decode(base32Secret)
  const counter = Math.floor(atMs / 1000 / stepSeconds)
  const counterBuffer = Buffer.alloc(8)
  counterBuffer.writeBigUInt64BE(BigInt(counter))

  const hmac = createHmac('sha1', key).update(counterBuffer).digest()
  const offset = hmac[hmac.length - 1] & 0x0f
  const binary =
    ((hmac[offset] & 0x7f) << 24) | ((hmac[offset + 1] & 0xff) << 16) | ((hmac[offset + 2] & 0xff) << 8) | (hmac[offset + 3] & 0xff)
  return (binary % 10 ** digits).toString().padStart(digits, '0')
}

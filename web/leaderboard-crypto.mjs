const textEncoder = new TextEncoder();


function canonicalValue(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("canonical JSON requires finite numbers");
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonicalValue(value[key])])
    );
  }
  throw new TypeError("unsupported canonical JSON value");
}


export function canonicalJson(value) {
  return JSON.stringify(canonicalValue(value));
}


function base64Url(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}


async function sha256Hex(value) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", textEncoder.encode(value)));
  return [...digest].map(byte => byte.toString(16).padStart(2, "0")).join("");
}


export async function encryptSubmission({summary, replay, keyId, publicKeyJwk}) {
  if (!globalThis.crypto?.subtle) throw new Error("当前浏览器不支持安全加密上传");
  const publicKey = await crypto.subtle.importKey(
    "jwk",
    publicKeyJwk,
    {name: "RSA-OAEP", hash: "SHA-256"},
    false,
    ["encrypt"],
  );
  const aesKey = await crypto.subtle.generateKey(
    {name: "AES-GCM", length: 256}, true, ["encrypt"]
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const additionalData = textEncoder.encode(canonicalJson(summary));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    {name: "AES-GCM", iv, additionalData, tagLength: 128},
    aesKey,
    textEncoder.encode(canonicalJson(replay)),
  ));
  const rawKey = new Uint8Array(await crypto.subtle.exportKey("raw", aesKey));
  const wrappedKey = new Uint8Array(await crypto.subtle.encrypt(
    {name: "RSA-OAEP"}, publicKey, rawKey
  ));
  const payload = {
    schema_version: 2,
    key_id: keyId,
    summary,
    encrypted_replay: {
      algorithm: "RSA-OAEP-3072+A256GCM",
      wrapped_key: base64Url(wrappedKey),
      iv: base64Url(iv),
      ciphertext: base64Url(ciphertext),
    },
  };
  return {
    ...payload,
    submission_id: (await sha256Hex(canonicalJson(payload))).slice(0, 20),
  };
}

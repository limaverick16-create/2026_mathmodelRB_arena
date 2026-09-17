import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import test from "node:test";

import {
  canonicalJson,
  encryptSubmission,
} from "../../web/leaderboard-crypto.mjs";
import {decryptSubmission} from "../../scripts/decrypt_submission.mjs";


function keys() {
  const {publicKey, privateKey} = generateKeyPairSync("rsa", {
    modulusLength: 3072,
    publicKeyEncoding: {type: "spki", format: "pem"},
    privateKeyEncoding: {type: "pkcs8", format: "pem"},
  });
  return {publicKey, privateKey};
}


async function publicJwkFromPem(pem) {
  const body = pem.replace(/-----[^-]+-----/g, "").replace(/\s/g, "");
  const bytes = Uint8Array.from(Buffer.from(body, "base64"));
  const key = await crypto.subtle.importKey(
    "spki", bytes, {name: "RSA-OAEP", hash: "SHA-256"}, true, ["encrypt"]
  );
  return crypto.subtle.exportKey("jwk", key);
}


const summary = {
  actor: "strategy",
  nickname: "小明",
  seconds_per_source: 12.5,
  source_count: 10,
};
const replay = {
  schema_version: 1,
  seed: 123456,
  actions: [{type: "move", x: 10, y: 20}],
};


test("canonical JSON is deterministic across key order", () => {
  assert.equal(
    canonicalJson({z: 1, nested: {b: "中文", a: 2}, a: [3, {y: 1, x: 2}]}),
    '{"a":[3,{"x":2,"y":1}],"nested":{"a":2,"b":"中文"},"z":1}'
  );
});


test("browser-compatible encryption round trips through trusted decryptor", async () => {
  const {publicKey, privateKey} = keys();
  const submission = await encryptSubmission({
    summary,
    replay,
    keyId: "arena-test-01",
    publicKeyJwk: await publicJwkFromPem(publicKey),
  });

  assert.deepEqual(decryptSubmission(submission, privateKey), replay);
  assert.equal(submission.schema_version, 2);
  assert.equal(submission.submission_id.length, 20);
  assert.equal("replay" in submission, false);
  assert.equal(JSON.stringify(submission).includes("123456"), false);
});


test("63-bit seed survives the browser JSON round-trip", async () => {
  const {publicKey, privateKey} = keys();
  const bigSeedReplay = {
    schema_version: 1,
    mode: "omnidirectional",
    seed: "7252035660260799000",  // 63-bit seed, serialized as a string
    source_count: 11,
    actions: [{type: "measure", channel: 1}],
    result: {virtual_time_s: 5.0},
  };
  // 模拟浏览器收到的 JSON 被 JSON.parse 后再 JSON.stringify 的往返。
  const roundTripped = JSON.parse(JSON.stringify(bigSeedReplay));
  const submission = await encryptSubmission({
    summary,
    replay: roundTripped,
    keyId: "arena-test-01",
    publicKeyJwk: await publicJwkFromPem(publicKey),
  });
  assert.equal(decryptSubmission(submission, privateKey).seed, "7252035660260799000");
});


test("summary or ciphertext tampering cannot be decrypted", async () => {
  const {publicKey, privateKey} = keys();
  const submission = await encryptSubmission({
    summary,
    replay,
    keyId: "arena-test-01",
    publicKeyJwk: await publicJwkFromPem(publicKey),
  });

  const changedSummary = structuredClone(submission);
  changedSummary.summary.nickname = "冒充者";
  assert.throws(() => decryptSubmission(changedSummary, privateKey));

  const changedCiphertext = structuredClone(submission);
  // 翻转中间字符，避免命中 base64url 去 padding 后的填充位（末字符低位可能不影响解码）。
  const ciphertext = changedCiphertext.encrypted_replay.ciphertext;
  const index = Math.floor(ciphertext.length / 2);
  changedCiphertext.encrypted_replay.ciphertext =
    ciphertext.slice(0, index) +
    (ciphertext[index] === "A" ? "B" : "A") +
    ciphertext.slice(index + 1);
  assert.throws(() => decryptSubmission(changedCiphertext, privateKey));
});

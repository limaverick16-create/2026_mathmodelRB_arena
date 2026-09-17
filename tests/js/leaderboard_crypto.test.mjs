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
  const last = changedCiphertext.encrypted_replay.ciphertext.at(-1);
  changedCiphertext.encrypted_replay.ciphertext =
    changedCiphertext.encrypted_replay.ciphertext.slice(0, -1) + (last === "A" ? "B" : "A");
  assert.throws(() => decryptSubmission(changedCiphertext, privateKey));
});

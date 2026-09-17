#!/usr/bin/env node

import {
  constants,
  createDecipheriv,
  privateDecrypt,
} from "node:crypto";
import {chmodSync, readFileSync, writeFileSync} from "node:fs";
import {pathToFileURL} from "node:url";

import {canonicalJson} from "../web/leaderboard-crypto.mjs";


export function decryptSubmissionRaw(submission, privateKeyPem) {
  if (submission?.encrypted_replay?.algorithm !== "RSA-OAEP-3072+A256GCM") {
    throw new Error("unsupported encryption algorithm");
  }
  const encrypted = submission.encrypted_replay;
  const aesKey = privateDecrypt(
    {
      key: privateKeyPem,
      padding: constants.RSA_PKCS1_OAEP_PADDING,
      oaepHash: "sha256",
    },
    Buffer.from(encrypted.wrapped_key, "base64url"),
  );
  const combined = Buffer.from(encrypted.ciphertext, "base64url");
  if (combined.length <= 16) throw new Error("encrypted replay is truncated");
  const ciphertext = combined.subarray(0, -16);
  const authTag = combined.subarray(-16);
  const decipher = createDecipheriv(
    "aes-256-gcm", aesKey, Buffer.from(encrypted.iv, "base64url")
  );
  decipher.setAAD(Buffer.from(canonicalJson(submission.summary), "utf8"));
  decipher.setAuthTag(authTag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return plaintext.toString("utf8");
}


export function decryptSubmission(submission, privateKeyPem) {
  return JSON.parse(decryptSubmissionRaw(submission, privateKeyPem));
}


function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`missing ${name}`);
  return process.argv[index + 1];
}


function main() {
  const input = argument("--submission");
  const output = argument("--output");
  const privateKey = process.env.LEADERBOARD_PRIVATE_KEY_PEM;
  if (!privateKey) throw new Error("leaderboard private key is not configured");
  const submission = JSON.parse(readFileSync(input, "utf8"));
  // 原样写出解密后的明文，不经过 JSON.parse/stringify，避免整数坐标 100.0 被
  // 改写为 100 而破坏回放哈希。
  const plaintext = decryptSubmissionRaw(submission, privateKey);
  writeFileSync(output, `${plaintext}\n`, {encoding: "utf8", mode: 0o600});
  chmodSync(output, 0o600);
}


if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main();
  } catch {
    console.error("encrypted replay validation failed");
    process.exitCode = 1;
  }
}

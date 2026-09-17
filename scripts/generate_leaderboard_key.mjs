#!/usr/bin/env node

import {createHash, generateKeyPairSync} from "node:crypto";
import {chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {homedir} from "node:os";


function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}


const configPath = argument("--config", "leaderboard/config.json");
const privatePath = argument(
  "--private-output",
  join(homedir(), "Library", "Application Support", "BProblemArena", "leaderboard-private-key.pem"),
);
const force = process.argv.includes("--force");
if (existsSync(privatePath) && !force) {
  throw new Error(`private key already exists: ${privatePath}`);
}

const {publicKey, privateKey} = generateKeyPairSync("rsa", {modulusLength: 3072});
const publicDer = publicKey.export({type: "spki", format: "der"});
const keyId = `arena-${createHash("sha256").update(publicDer).digest("hex").slice(0, 16)}`;
const publicJwk = publicKey.export({format: "jwk"});
publicJwk.alg = "RSA-OAEP-256";
publicJwk.key_ops = ["encrypt"];
publicJwk.ext = true;

mkdirSync(dirname(privatePath), {recursive: true, mode: 0o700});
writeFileSync(
  privatePath,
  privateKey.export({type: "pkcs8", format: "pem"}),
  {encoding: "utf8", mode: 0o600},
);
chmodSync(privatePath, 0o600);

const config = JSON.parse(readFileSync(configPath, "utf8"));
config.encryption_key_id = keyId;
config.encryption_public_key_jwk = publicJwk;
writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
console.log(`generated leaderboard key ${keyId}`);
console.log(`private key saved outside the repository: ${privatePath}`);

#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const APP_ID = process.env.GITHUB_APP_ID || '5459882';

function findPrivateKey() {
  const candidates = [
    process.env.GITHUB_APP_KEY_PATH,
    path.join(os.homedir(), '.config', 'gh-bot', 'private-key.pem'),
    path.join(os.homedir(), '.config', 'github-apps', 'antigravity-lp-reviewer.private-key.pem'),
    path.join(__dirname, '..', 'private-key.pem'),
    path.join(__dirname, 'private-key.pem')
  ].filter(Boolean);

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return fs.readFileSync(p, 'utf8');
    }
  }

  throw new Error(`Private key not found. Looked in:\n  ${candidates.join('\n  ')}`);
}

function createJWT(appId, pem) {
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
  const now = Math.floor(Date.now() / 1000);
  const payload = Buffer.from(JSON.stringify({
    iat: now - 60,
    exp: now + (9 * 60),
    iss: appId
  })).toString('base64url');

  const sign = crypto.createSign('RSA-SHA256');
  sign.update(`${header}.${payload}`);
  const signature = sign.sign(pem, 'base64url');
  return `${header}.${payload}.${signature}`;
}

const cacheDir = path.join(os.homedir(), '.config', 'gh-bot');
const cachePath = path.join(cacheDir, 'token-cache.json');

async function getInstallationToken(privateKey) {
  if (fs.existsSync(cachePath)) {
    try {
      const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
      if (cache.token && cache.expires_at) {
        const expires = new Date(cache.expires_at).getTime();
        // Reuse cached token if valid for at least 2 more minutes
        if (expires - Date.now() > 2 * 60 * 1000) {
          return cache.token;
        }
      }
    } catch (_) {}
  }

  const jwt = createJWT(APP_ID, privateKey);
  const instRes = await fetch('https://api.github.com/app/installations', {
    headers: {
      Authorization: `Bearer ${jwt}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'gh-as-bot'
    }
  });

  if (!instRes.ok) {
    const err = await instRes.text();
    throw new Error(`Failed to list installations (${instRes.status}): ${err}`);
  }

  const installations = await instRes.json();
  if (!installations || installations.length === 0) {
    throw new Error('No installations found for GitHub App.');
  }

  const installationId = installations[0].id;
  const tokenRes = await fetch(`https://api.github.com/app/installations/${installationId}/access_tokens`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${jwt}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'gh-as-bot'
    }
  });

  if (!tokenRes.ok) {
    const err = await tokenRes.text();
    throw new Error(`Failed to mint access token (${tokenRes.status}): ${err}`);
  }

  const tokenData = await tokenRes.json();
  try {
    if (!fs.existsSync(cacheDir)) {
      fs.mkdirSync(cacheDir, { recursive: true });
    }
    fs.writeFileSync(cachePath, JSON.stringify(tokenData));
  } catch (_) {}

  return tokenData.token;
}

async function main() {
  const privateKey = findPrivateKey();
  const token = await getInstallationToken(privateKey);
  const args = process.argv.slice(2);

  const isWindows = process.platform === 'win32';
  const ghCommand = isWindows ? 'gh.exe' : 'gh';

  const result = spawnSync(ghCommand, args, {
    env: {
      ...process.env,
      GH_TOKEN: token,
      GITHUB_TOKEN: token
    },
    stdio: 'inherit'
  });

  if (result.error) {
    console.error('Failed to run gh:', result.error);
    process.exit(1);
  }

  process.exit(result.status ?? 0);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});

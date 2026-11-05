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

function resolveTargetOwner(args) {
  if (process.env.GITHUB_APP_INSTALLATION_LOGIN) {
    return process.env.GITHUB_APP_INSTALLATION_LOGIN;
  }
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if ((arg === '-R' || arg === '--repo') && args[i + 1]) {
      const parts = args[i + 1].split('/');
      if (parts.length >= 2) return parts[0];
    }
    const repoMatch = /^repos\/([^/]+)\/[^/]+/.exec(arg);
    if (repoMatch && repoMatch[1] !== '{owner}') {
      return repoMatch[1];
    }
  }
  try {
    const remote = spawnSync('git', ['config', '--get', 'remote.origin.url'], { encoding: 'utf8' });
    if (remote.status === 0 && remote.stdout) {
      const m = /github\.com[:/]([^/]+)\//.exec(remote.stdout.trim());
      if (m) return m[1];
    }
  } catch (_) {}
  return null;
}

function getCachePath(appId, installationKey) {
  const safeApp = String(appId).replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeInst = String(installationKey || 'default').replace(/[^a-zA-Z0-9_-]/g, '_');
  return path.join(cacheDir, `token-cache-${safeApp}-${safeInst}.json`);
}

async function getInstallationToken(privateKey, args) {
  const explicitInstallationId = process.env.GITHUB_APP_INSTALLATION_ID || null;
  const targetOwner = resolveTargetOwner(args);
  const cacheKey = explicitInstallationId || (targetOwner ? targetOwner.toLowerCase() : 'default');
  const cachePath = getCachePath(APP_ID, cacheKey);

  if (fs.existsSync(cachePath)) {
    try {
      if (process.platform !== 'win32') {
        fs.chmodSync(cachePath, 0o600);
      }
      const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
      if (
        cache.token &&
        cache.expires_at &&
        String(cache.app_id) === String(APP_ID) &&
        (!explicitInstallationId || String(cache.installation_id) === String(explicitInstallationId))
      ) {
        const expires = new Date(cache.expires_at).getTime();
        // Reuse cached token if valid for at least 2 more minutes
        if (expires - Date.now() > 2 * 60 * 1000) {
          return cache.token;
        }
      }
    } catch (_) {}
  }

  const jwt = createJWT(APP_ID, privateKey);
  let installationId = explicitInstallationId;

  if (!installationId) {
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

    let matched = null;
    if (targetOwner) {
      matched = installations.find(
        (inst) => inst.account && inst.account.login && inst.account.login.toLowerCase() === targetOwner.toLowerCase()
      );
    }
    if (!matched) {
      if (installations.length === 1) {
        matched = installations[0];
      } else {
        const logins = installations.map((i) => `${i.account?.login} (${i.id})`).join(', ');
        throw new Error(
          `Multiple installations found (${logins}) and none matched target owner '${targetOwner || 'unknown'}'. ` +
          `Set GITHUB_APP_INSTALLATION_ID or GITHUB_APP_INSTALLATION_LOGIN.`
        );
      }
    }
    installationId = matched.id;
  }

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
      fs.mkdirSync(cacheDir, { recursive: true, mode: 0o700 });
    } else if (process.platform !== 'win32') {
      fs.chmodSync(cacheDir, 0o700);
    }
    const cachePayload = JSON.stringify({
      ...tokenData,
      app_id: APP_ID,
      installation_id: installationId
    });
    fs.writeFileSync(cachePath, cachePayload, { mode: 0o600 });
    if (process.platform !== 'win32') {
      fs.chmodSync(cachePath, 0o600);
    }
  } catch (_) {}

  return tokenData.token;
}

async function main() {
  const args = process.argv.slice(2);
  const privateKey = findPrivateKey();
  const token = await getInstallationToken(privateKey, args);

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

  if (result.signal) {
    console.error(`gh terminated by signal: ${result.signal}`);
    process.exit(1);
  }

  process.exit(result.status ?? 1);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});

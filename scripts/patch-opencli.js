#!/usr/bin/env node
/**
 * Post-install patch for @jackwener/opencli (CommonJS, works on Node 18+).
 *
 * Usage:
 *   node patch-opencli.js               # patch the default global install
 *   node patch-opencli.js /opt/my-dir   # patch a specific npm prefix dir
 *
 * Adds two env-var hooks that the published package lacks:
 *
 *   OPENCLI_DAEMON_LISTEN  (daemon.js)
 *     Default: 127.0.0.1 — set to 0.0.0.0 so the API container can reach
 *     the daemon running inside the chrome-N container.
 *
 *   OPENCLI_DAEMON_HOST  (daemon-client.js + browser/bridge.js)
 *     Default: 127.0.0.1 — set to chrome-1 (or chrome-N) so the CLI in the
 *     API container contacts the remote daemon instead of spawning one locally.
 *
 * v1.7.0 migration: mcp.js renamed to browser/bridge.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

function resolvePackageDir(prefixDir) {
  if (prefixDir) {
    // Explicit prefix supplied (e.g. /opt/opencli-bridge)
    const candidate = path.join(prefixDir, 'lib', 'node_modules', '@jackwener', 'opencli');
    if (fs.existsSync(candidate)) return candidate;
    // Some npm versions omit the 'lib/' level
    const candidate2 = path.join(prefixDir, 'node_modules', '@jackwener', 'opencli');
    if (fs.existsSync(candidate2)) return candidate2;
    throw new Error('Could not find @jackwener/opencli under prefix: ' + prefixDir);
  }
  try {
    return path.dirname(require.resolve('@jackwener/opencli/package.json'));
  } catch (_) {
    // Fallback: ask npm where its global root is (works with NodeSource installs)
    const { execSync } = require('child_process');
    const npmRoot = execSync('npm root -g').toString().trim();
    return path.join(npmRoot, '@jackwener', 'opencli');
  }
}

function patch(filePath, search, replace, label) {
  if (!fs.existsSync(filePath)) {
    console.log('  [skip] ' + label + ': file not found ' + filePath);
    return;
  }
  let content = fs.readFileSync(filePath, 'utf8');
  if (content.includes(replace)) {
    console.log('  [skip] ' + label + ' already patched');
    return;
  }
  if (!content.includes(search)) {
    console.error('  [warn] ' + label + ': search string not found in ' + filePath);
    return;
  }
  content = content.replace(search, replace);
  fs.writeFileSync(filePath, content);
  console.log('  [ok]   ' + label);
}

const prefixDir = process.argv[2] || null;
const pkgDir = resolvePackageDir(prefixDir);
console.log('Patching opencli at ' + pkgDir + ' ...');

// ── 1. daemon.js: honour OPENCLI_DAEMON_LISTEN ───────────────────────────────
patch(
  path.join(pkgDir, 'dist', 'daemon.js'),
  "httpServer.listen(PORT, '127.0.0.1', () => {",
  "const DAEMON_LISTEN = process.env.OPENCLI_DAEMON_LISTEN ?? '127.0.0.1';\nhttpServer.listen(PORT, DAEMON_LISTEN, () => {",
  'daemon.js: OPENCLI_DAEMON_LISTEN'
);

// ── 2. daemon-client.js: honour OPENCLI_DAEMON_HOST ─────────────────────────
patch(
  path.join(pkgDir, 'dist', 'browser', 'daemon-client.js'),
  'const DAEMON_URL = `http://127.0.0.1:${DAEMON_PORT}`;',
  "const DAEMON_HOST = process.env.OPENCLI_DAEMON_HOST ?? '127.0.0.1';\nconst DAEMON_URL = `http://${DAEMON_HOST}:${DAEMON_PORT}`;",
  'daemon-client.js: OPENCLI_DAEMON_HOST'
);

// ── 3. browser/bridge.js: skip local auto-spawn when daemon is remote ────────
// v1.7.0+: _ensureDaemon moved from mcp.js to browser/bridge.js.
// When OPENCLI_DAEMON_HOST is set to a remote address, we must NOT try to
// spawn a local daemon process — throw immediately so the caller surfaces a
// clear error rather than silently starting a useless local daemon.
patch(
  path.join(pkgDir, 'dist', 'browser', 'bridge.js'),
  'const __dirname = path.dirname(fileURLToPath(import.meta.url));',
  "const _dHost = process.env.OPENCLI_DAEMON_HOST;\n        if (_dHost && _dHost !== '127.0.0.1' && _dHost !== 'localhost') {\n            throw new Error('Remote Browser Bridge daemon at ' + _dHost + ' is not reachable. Ensure BROWSER_BRIDGE_ENABLED=true on the chrome container.');\n        }\n        const __dirname = path.dirname(fileURLToPath(import.meta.url));",
  'browser/bridge.js: skip local spawn for remote daemon'
);

// ── 4. douyin/user-videos.js: expose public publication and engagement data ─
// The upstream public adapter currently drops create_time and most counters
// before serialising rows.  The monitor cannot calculate an age-aware baseline
// or seven-day observation window without this field, so keep the enrichment
// as a small, repeatable post-install patch rather than forking opencli.
patch(
  path.join(pkgDir, 'clis', 'douyin', 'user-videos.js'),
  "    columns: ['index', 'aweme_id', 'title', 'duration', 'digg_count', 'play_url', 'top_comments'],",
  `    columns: [
        'index', 'aweme_id', 'title', 'duration', 'published_at', 'url',
        'digg_count', 'comment_count', 'collect_count', 'share_count',
        'play_count', 'play_url', 'top_comments',
    ],`,
  'douyin/user-videos.js: publication and engagement fields'
);
patch(
  path.join(pkgDir, 'clis', 'douyin', 'user-videos.js'),
  `            const playUrl = video.video?.play_addr?.url_list?.[0] ?? '';
            return {
                index: index + 1,
                aweme_id: video.aweme_id,
                title: video.desc ?? '',
                duration: Math.round((video.video?.duration ?? 0) / 1000),
                digg_count: video.statistics?.digg_count ?? 0,
                play_url: playUrl,
                top_comments: video.top_comments ?? [],
            };`,
  `            const playUrl = video.video?.play_addr?.url_list?.[0] ?? '';
            const createTime = Number(video.create_time ?? video.public_time ?? 0);
            const statistics = video.statistics ?? {};
            return {
                index: index + 1,
                aweme_id: video.aweme_id,
                title: video.desc ?? '',
                duration: Math.round((video.video?.duration ?? 0) / 1000),
                published_at: createTime > 0 ? new Date(createTime * 1000).toISOString() : '',
                url: video.aweme_id ? 'https://www.douyin.com/video/' + video.aweme_id : '',
                digg_count: statistics.digg_count ?? 0,
                comment_count: statistics.comment_count ?? 0,
                collect_count: statistics.collect_count ?? statistics.collects_count ?? 0,
                share_count: statistics.share_count ?? 0,
                play_count: statistics.play_count ?? 0,
                play_url: playUrl,
                top_comments: video.top_comments ?? [],
            };`,
  'douyin/user-videos.js: map publication and engagement fields'
);
patch(
  path.join(pkgDir, 'clis', 'douyin', 'user-videos.js'),
  "        'index', 'aweme_id', 'title', 'duration', 'published_at',\n        'digg_count',",
  "        'index', 'aweme_id', 'title', 'duration', 'published_at', 'url',\n        'digg_count',",
  'douyin/user-videos.js: stable work URL column'
);
patch(
  path.join(pkgDir, 'clis', 'douyin', 'user-videos.js'),
  "                published_at: createTime > 0 ? new Date(createTime * 1000).toISOString() : '',\n                digg_count:",
  "                published_at: createTime > 0 ? new Date(createTime * 1000).toISOString() : '',\n                url: video.aweme_id ? 'https://www.douyin.com/video/' + video.aweme_id : '',\n                digg_count:",
  'douyin/user-videos.js: stable work URL value'
);

console.log('Done.');

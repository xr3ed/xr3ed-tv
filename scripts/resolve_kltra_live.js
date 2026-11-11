#!/usr/bin/env node
/**
 * resolve_kltra_live.js
 * =====================
 * High-speed Direct Resolver for Kltra TV (live.kltratv.site).
 * Ported directly from reverse-engineered WebCrypto ECDSA P-256 handshake:
 * - Generates ephemeral client EC P-256 keypair
 * - Registers visitor session via /visitor endpoint
 * - Signs IEEE P1363 ECDSA SHA-256 proof for /session
 * - Obtains TopParser gateway session token
 * - Resolves direct iframe and extracts playable .m3u8 stream URL
 * - Fallback to Chrome CDP if pure HTTP resolution fails
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const https = require('https');

const crypto = globalThis.crypto;
const DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';

function base64url(buf) {
    return Buffer.from(buf).toString('base64')
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
}

async function fetchJson(url, headers = {}) {
    try {
        const res = await fetch(url, { headers });
        if (res.ok) return await res.json();
    } catch (e) {}
    return null;
}

async function createVisitorSession() {
    try {
        const keyPair = await crypto.subtle.generateKey(
            { name: 'ECDSA', namedCurve: 'P-256' },
            true,
            ['sign', 'verify']
        );
        const pubJwk = await crypto.subtle.exportKey('jwk', keyPair.publicKey);
        const vRes = await fetch('https://kltra-event-api.elutuna.workers.dev/visitor', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'User-Agent': DESKTOP_UA,
                'Origin': 'https://live.kltratv.site',
                'Referer': 'https://live.kltratv.site/'
            },
            body: JSON.stringify({
                publicKey: {
                    kty: pubJwk.kty,
                    crv: pubJwk.crv,
                    x: pubJwk.x,
                    y: pubJwk.y
                }
            })
        });
        if (!vRes.ok) {
            console.error(`[Visitor Error] status=${vRes.status}`);
            return null;
        }
        const vData = await vRes.json();
        return { token: vData.accessToken, keyPair };
    } catch (e) {
        console.error(`[Visitor Exception] ${e.message}`);
        return null;
    }
}

async function resolvePureHttp(liveItems) {
    console.error(`[Pure HTTP] Resolving ${liveItems.length} live matches via WebCrypto ECDSA P-256...`);
    const pools = await Promise.all([
        createVisitorSession(),
        createVisitorSession(),
        createVisitorSession()
    ]);
    const validPools = pools.filter(Boolean);
    if (validPools.length === 0) {
        console.error("[Pure HTTP] Failed to create visitor session pools.");
        return {};
    }

    async function resolveSingle(it, sessionIndex) {
        if (!it.broadcastId) return null;
        let s = validPools[sessionIndex % validPools.length];

        for (let attempt = 0; attempt < 2; attempt++) {
            const issuedAt = Date.now();
            const nonceBuf = new Uint8Array(16);
            crypto.getRandomValues(nonceBuf);
            const nonce = base64url(nonceBuf);
            const bodyObj = { eventId: String(it.id), force: false };

            const signPayload = [
                'POST',
                'https://kltra-event-api.elutuna.workers.dev',
                '/session',
                s.token,
                String(issuedAt),
                nonce,
                JSON.stringify(bodyObj)
            ].join('\n');

            const sigBuf = await crypto.subtle.sign(
                { name: 'ECDSA', hash: { name: 'SHA-256' } },
                s.keyPair.privateKey,
                new TextEncoder().encode(signPayload)
            );

            let sRes;
            try {
                sRes = await fetch('https://kltra-event-api.elutuna.workers.dev/session', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'User-Agent': DESKTOP_UA,
                        'Authorization': `Bearer ${s.token}`,
                        'Origin': 'https://live.kltratv.site',
                        'Referer': 'https://live.kltratv.site/'
                    },
                    body: JSON.stringify({
                        eventId: String(it.id),
                        force: false,
                        proof: { issuedAt, nonce, signature: base64url(sigBuf) }
                    })
                });
            } catch (e) {
                console.error(`[Session Fetch Err ${it.id}] ${e.message}`);
                return null;
            }

            if (sRes.status === 429) {
                await new Promise(r => setTimeout(r, 400));
                const newS = await createVisitorSession();
                if (newS) s = newS;
                continue;
            }

            if (!sRes.ok) {
                const errTxt = await sRes.text();
                console.error(`[Session Err ${it.id}] status=${sRes.status} body=${errTxt.substring(0, 100)}`);
                return null;
            }
            const sData = await sRes.json();
            const sessionToken = sData.sessionToken;
            if (!sessionToken) return null;

            let tpRes;
            try {
                tpRes = await fetch('https://api-gateway.top-parser.com/broadcast/get-url', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'User-Agent': DESKTOP_UA,
                        'X-External-Partner-Id': '44ba10e5-7df2-47ab-a44d-dc93803c7a6e',
                        'Token': sessionToken,
                        'X-Lang': 'en-001',
                        'X-User-Location': 'ID',
                        'Origin': 'https://live.kltratv.site',
                        'Referer': 'https://live.kltratv.site/'
                    },
                    body: JSON.stringify({ id: it.broadcastId })
                });
            } catch (e) {
                console.error(`[TopParser Fetch Err ${it.id}] ${e.message}`);
                return null;
            }

            if (!tpRes.ok) {
                const errTxt = await tpRes.text();
                console.error(`[TopParser Err ${it.id}] status=${tpRes.status} body=${errTxt.substring(0, 100)}`);
                return null;
            }
            const tpData = await tpRes.json();
            const iframeUrl = tpData.url || (tpData.result && tpData.result.url);
            if (!iframeUrl) return null;

            try {
                const iframeRes = await fetch(iframeUrl, {
                    headers: {
                        'User-Agent': DESKTOP_UA,
                        'Referer': 'https://live.kltratv.site/'
                    }
                });
                const html = await iframeRes.text();
                const m = html.match(/hls\.loadSource\(['"]([^'"]+)['"]\)/) || html.match(/video\.src\s*=\s*['"]([^'"]+)['"]/);
                if (m) {
                    console.error(`[RESOLVED PURE] ${it.id} -> ${m[1].substring(0, 60)}...`);
                    return { id: it.id, url: m[1] };
                } else {
                    console.error(`[Iframe No M3U8 ${it.id}] html=${html.substring(0, 120)}`);
                }
            } catch (e) {
                console.error(`[Iframe Fetch Err ${it.id}] ${e.message}`);
            }
            return null;
        }
        return null;
    }

    const resultMap = {};
    const concurrency = 4;
    for (let i = 0; i < liveItems.length; i += concurrency) {
        const batch = liveItems.slice(i, i + concurrency);
        const resolved = await Promise.all(batch.map((it, idx) => resolveSingle(it, i + idx)));
        for (const r of resolved) {
            if (r && r.url) {
                resultMap[r.id] = r.url;
            }
        }
        await new Promise(r => setTimeout(r, 150));
    }
    return resultMap;
}

function findChromeBinary() {
    const candidates = [
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/snap/bin/chromium'
    ];
    for (const c of candidates) {
        try {
            if (fs.existsSync(c)) return c;
        } catch (e) {}
    }
    if (process.platform !== 'win32') {
        try {
            const out = execSync('which google-chrome || which google-chrome-stable || which chromium-browser || which chromium', {
                stdio: ['pipe', 'pipe', 'ignore'],
                encoding: 'utf8'
            }).trim();
            const lines = out.split('\n');
            for (const line of lines) {
                const bin = line.trim();
                if (bin && fs.existsSync(bin)) return bin;
            }
        } catch (e) {}
    }
    return null;
}

async function resolveCdpFallback(liveItems, missingIds) {
    const WS = globalThis.WebSocket || (() => {
        try { return require('undici').WebSocket; } catch (e) { return null; }
    })();
    if (!WS) return {};

    const chromeBin = findChromeBinary();
    if (!chromeBin) return {};

    const itemsToResolve = liveItems.filter(it => missingIds.includes(String(it.id))).slice(0, 10);
    if (itemsToResolve.length === 0) return {};

    console.error(`[CDP Fallback] Resolving ${itemsToResolve.length} matches via Chrome CDP...`);
    const port = 9235;
    const profileDir = path.join(os.tmpdir(), 'chrome_cdp_kltra_fallback');
    try { fs.mkdirSync(profileDir, { recursive: true }); } catch (e) {}

    let devtoolsListening = false;
    const chrome = spawn(chromeBin, [
        '--headless=new',
        `--remote-debugging-port=${port}`,
        '--remote-debugging-address=0.0.0.0',
        '--disable-gpu',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--no-first-run',
        `--user-agent=${DESKTOP_UA}`,
        `--user-data-dir=${profileDir}`
    ]);

    chrome.stderr.on('data', d => {
        const msg = d.toString();
        if (msg.includes('DevTools listening on')) devtoolsListening = true;
    });

    for (let i = 0; i < 30; i++) {
        if (devtoolsListening) break;
        await new Promise(r => setTimeout(r, 200));
    }

    function resolveOne(id) {
        return new Promise((resolve) => {
            const targetUrl = `https://live.kltratv.site/playersd?key=liveevents-${id}-1`;
            const req = http.request({
                host: '127.0.0.1',
                port: port,
                path: '/json/new?' + targetUrl,
                method: 'PUT'
            }, (res) => {
                let body = '';
                res.on('data', c => body += c);
                res.on('end', () => {
                    let page;
                    try { page = JSON.parse(body); } catch (e) { return resolve(null); }
                    if (!page || !page.webSocketDebuggerUrl) return resolve(null);

                    let finished = false;
                    let timeout = null;
                    let ws = null;

                    const cleanup = () => {
                        if (finished) return;
                        finished = true;
                        clearTimeout(timeout);
                        if (ws) {
                            try { ws.close(); } catch (e) {}
                        }
                        if (page && page.id) {
                            const closeReq = http.request({ host: '127.0.0.1', port: port, path: '/json/close/' + page.id, method: 'PUT' });
                            closeReq.on('error', () => {});
                            closeReq.end();
                        }
                    };

                    try {
                        ws = new WS(page.webSocketDebuggerUrl);
                    } catch (e) {
                        cleanup();
                        return resolve(null);
                    }

                    let msgId = 1;
                    ws.onopen = () => {
                        ws.send(JSON.stringify({ id: msgId++, method: 'Network.enable' }));
                        ws.send(JSON.stringify({
                            id: msgId++,
                            method: 'Network.setBlockedURLs',
                            params: { urls: ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.woff*'] }
                        }));
                    };

                    ws.onmessage = async (event) => {
                        if (finished) return;
                        try {
                            const msg = JSON.parse(event.data);
                            if (msg.method === 'Network.requestWillBeSent') {
                                const r = msg.params.request;
                                if (r.url.includes('.m3u8') && (r.url.includes('smytdryt') || r.url.includes('match_id='))) {
                                    cleanup();
                                    return resolve({ id, streamUrl: r.url });
                                }
                                if (r.url.includes('video-translations.top-parser.com/sm/iframe')) {
                                    const iframeRes = await fetch(r.url, {
                                        headers: { 'User-Agent': DESKTOP_UA }
                                    });
                                    const html = await iframeRes.text();
                                    const m = html.match(/hls\.loadSource\(['"]([^'"]+)['"]\)/) || html.match(/video\.src\s*=\s*['"]([^'"]+)['"]/);
                                    if (m) {
                                        cleanup();
                                        return resolve({ id, streamUrl: m[1] });
                                    }
                                }
                            }
                        } catch (e) {}
                    };

                    ws.onerror = () => {
                        cleanup();
                        resolve(null);
                    };

                    timeout = setTimeout(() => {
                        cleanup();
                        resolve(null);
                    }, 10000);
                });
            });
            req.on('error', () => resolve(null));
            req.end();
        });
    }

    const fallbackMap = {};
    for (const it of itemsToResolve) {
        const r = await resolveOne(it.id);
        if (r && r.streamUrl) {
            fallbackMap[r.id] = r.streamUrl;
        }
    }
    try { chrome.kill(); } catch (e) {}
    return fallbackMap;
}

async function main() {
    const workerUrl = 'https://kltra-event-api.elutuna.workers.dev/events.json';
    const evData = await fetchJson(workerUrl, {
        'User-Agent': DESKTOP_UA,
        'Origin': 'https://live.kltratv.site',
        'Referer': 'https://live.kltratv.site/'
    });

    if (!evData || !evData.items) {
        console.log("{}");
        return;
    }

    const nowMs = Date.now();
    const liveItems = evData.items.filter(it => {
        const start = it.start || 0;
        return (start <= nowMs && (nowMs - start) < 3.5 * 3600 * 1000);
    });

    console.error(`Found ${liveItems.length} currently live worker events.`);
    if (liveItems.length === 0) {
        console.log("{}");
        return;
    }

    // Step 1: Pure HTTP WebCrypto resolution (primary, ultra-fast & resilient)
    let resultMap = await resolvePureHttp(liveItems);
    console.error(`[Pure HTTP] Successfully resolved ${Object.keys(resultMap).length} / ${liveItems.length} streams.`);

    // Step 2: Fallback to CDP for remaining matches if needed
    const resolvedIds = Object.keys(resultMap);
    const missingIds = liveItems.map(it => String(it.id)).filter(id => !resolvedIds.includes(id));
    if (missingIds.length > 0 && resolvedIds.length < 5) {
        const cdpMap = await resolveCdpFallback(liveItems, missingIds);
        resultMap = { ...resultMap, ...cdpMap };
    }

    console.log(JSON.stringify(resultMap));
}

main().catch(err => {
    console.error("Main error:", err);
    console.log("{}");
});

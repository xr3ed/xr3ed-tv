const { spawn } = require('child_process');
const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');

const WS = globalThis.WebSocket || (() => {
    try { return require('undici').WebSocket; } catch (e) { return null; }
})();

async function fetchJson(url, headers = {}) {
    return new Promise((resolve) => {
        try {
            const u = new URL(url);
            const lib = u.protocol === 'https:' ? https : http;
            const req = lib.request(url, { headers }, res => {
                let data = '';
                res.on('data', c => data += c);
                res.on('end', () => {
                    try { resolve(JSON.parse(data)); } catch (e) { resolve(null); }
                });
            });
            req.on('error', () => resolve(null));
            req.setTimeout(5000, () => { req.destroy(); resolve(null); });
            req.end();
        } catch (e) {
            resolve(null);
        }
    });
}

async function waitForChrome(port, maxTries = 25) {
    for (let i = 0; i < maxTries; i++) {
        try {
            const ok = await new Promise((res) => {
                const req = http.get(`http://127.0.0.1:${port}/json/version`, r => {
                    res(r.statusCode === 200);
                });
                req.on('error', () => res(false));
                req.setTimeout(600, () => { req.destroy(); res(false); });
            });
            if (ok) return true;
        } catch (e) {}
        await new Promise(r => setTimeout(r, 200));
    }
    return false;
}

async function main() {
    if (!WS) {
        console.error("Error: WebSocket not available in Node runtime.");
        console.log("{}");
        return;
    }

    const workerUrl = 'https://kltra-event-api.elutuna.workers.dev/events.json';
    const evData = await fetchJson(workerUrl, {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Origin': 'https://live.kltratv.site'
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

    const chromeCandidates = [
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        'google-chrome',
        'google-chrome-stable',
        'chromium',
        'chrome'
    ];
    let chromeBin = null;
    for (let c of chromeCandidates) {
        try {
            if (c.includes('\\') || c.startsWith('/')) {
                if (fs.existsSync(c)) {
                    chromeBin = c;
                    break;
                }
            } else {
                chromeBin = c;
                break;
            }
        } catch (e) {}
    }

    if (!chromeBin) {
        console.error("Chrome binary not found.");
        console.log("{}");
        return;
    }

    const port = 9235;
    const profileDir = path.join(os.tmpdir(), 'chrome_cdp_kltra_live');
    try { fs.mkdirSync(profileDir, { recursive: true }); } catch (e) {}

    const chrome = spawn(chromeBin, [
        '--headless=new',
        `--remote-debugging-port=${port}`,
        '--disable-gpu',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-software-rasterizer',
        `--user-data-dir=${profileDir}`,
        '--no-first-run'
    ]);

    chrome.stderr.on('data', d => {
        const msg = d.toString();
        if (msg.includes('ERROR') || msg.includes('FATAL')) {
            console.error('[CHROME LOG]', msg.trim());
        }
    });

    const ready = await waitForChrome(port);
    if (!ready) {
        console.error("Chrome failed to bind remote debugging port.");
        try { chrome.kill(); } catch (e) {}
        console.log("{}");
        return;
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
                                    const iframeRes = await new Promise(resDone => {
                                        https.get(r.url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, res2 => {
                                            let h = '';
                                            res2.on('data', d => h += d);
                                            res2.on('end', () => resDone(h));
                                        }).on('error', () => resDone(''));
                                    });
                                    const m = iframeRes.match(/hls\.loadSource\(['"]([^'"]+)['"]\)/) || iframeRes.match(/video\.src\s*=\s*['"]([^'"]+)['"]/);
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
                    }, 7000);
                });
            });
            req.on('error', () => resolve(null));
            req.end();
        });
    }

    const resultMap = {};
    const queue = liveItems.slice(0, 30);
    const concurrency = 6;
    for (let i = 0; i < queue.length; i += concurrency) {
        const batch = queue.slice(i, i + concurrency);
        const resolved = await Promise.all(batch.map(it => resolveOne(it.id)));
        for (let r of resolved) {
            if (r && r.streamUrl) {
                resultMap[r.id] = r.streamUrl;
                console.error(`[RESOLVED] ${r.id}`);
            }
        }
    }

    try { chrome.kill(); } catch (e) {}
    console.log(JSON.stringify(resultMap));
}

main().catch(err => {
    console.error("Main error:", err);
    console.log("{}");
});

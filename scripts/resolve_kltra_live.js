const { spawn, execSync } = require('child_process');
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

async function waitForChrome(port, isDevtoolsReady, maxTries = 35) {
    for (let i = 0; i < maxTries; i++) {
        if (isDevtoolsReady()) return true;
        try {
            const ok = await new Promise((res) => {
                const req = http.get(`http://127.0.0.1:${port}/json/version`, r => {
                    res(r.statusCode === 200);
                });
                req.on('error', () => {
                    const req2 = http.get(`http://localhost:${port}/json/version`, r2 => {
                        res(r2.statusCode === 200);
                    });
                    req2.on('error', () => res(false));
                    req2.setTimeout(400, () => { req2.destroy(); res(false); });
                });
                req.setTimeout(400, () => { req2 = null; req.destroy(); res(false); });
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

    const chromeBin = findChromeBinary();
    if (!chromeBin) {
        console.error("Chrome binary not found on this system.");
        console.log("{}");
        return;
    }
    console.error(`Using Chrome binary: ${chromeBin}`);

    const port = 9235;
    const profileDir = path.join(os.tmpdir(), 'chrome_cdp_kltra_live');
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
        '--disable-software-rasterizer',
        '--no-first-run',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        `--user-data-dir=${profileDir}`
    ]);

    chrome.stderr.on('data', d => {
        const msg = d.toString();
        if (msg.includes('DevTools listening on')) {
            devtoolsListening = true;
            console.error('[CHROME READY]', msg.trim());
        } else if (msg.includes('ERROR') || msg.includes('FATAL')) {
            console.error('[CHROME ERR]', msg.trim());
        }
    });

    chrome.on('error', err => {
        console.error('[CHROME SPAWN ERROR]', err.message);
    });

    chrome.on('exit', (code, sig) => {
        if (code !== null && code !== 0) {
            console.error(`[CHROME EXITED] code=${code} signal=${sig}`);
        }
    });

    const ready = await waitForChrome(port, () => devtoolsListening);
    if (!ready) {
        console.error("Chrome failed to bind remote debugging port after 7s.");
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
                        // Block static media to speed up load time by 300%
                        ws.send(JSON.stringify({
                            id: msgId++,
                            method: 'Network.setBlockedURLs',
                            params: {
                                urls: ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.woff*', '*.ttf', '*googletagmanager*', '*analytics*']
                            }
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
                    }, 12000);
                });
            });
            req.on('error', () => resolve(null));
            req.end();
        });
    }

    const resultMap = {};
    const queue = liveItems.slice(0, 25);
    const concurrency = 3;
    console.error(`Resolving up to ${queue.length} live worker events (concurrency=${concurrency})...`);
    for (let i = 0; i < queue.length; i += concurrency) {
        const batch = queue.slice(i, i + concurrency);
        const resolved = await Promise.all(batch.map(it => resolveOne(it.id)));
        for (let r of resolved) {
            if (r && r.streamUrl) {
                resultMap[r.id] = r.streamUrl;
                console.error(`[RESOLVED] ${r.id} -> ${r.streamUrl.substring(0, 60)}...`);
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

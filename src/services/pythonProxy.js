const http = require('http');
const https = require('https');
const { pythonBaseUrl, backendPortCandidates } = require('../config/env');

function resolvePythonBaseUrl() {
  if (process.env.PYTHON_BASE_URL) {
    return process.env.PYTHON_BASE_URL;
  }

  return new Promise((resolve) => {
    const candidates = backendPortCandidates.map((port) => `http://127.0.0.1:${port}`);
    let index = 0;

    const probe = () => {
      if (index >= candidates.length) {
        resolve('http://127.0.0.1:8000');
        return;
      }

      const target = candidates[index];
      index += 1;

      const client = target.startsWith('https') ? https : http;
      const req = client.get(`${target}/api/health`, (res) => {
        const { statusCode } = res;
        let raw = '';

        res.on('data', (chunk) => {
          raw += chunk;
        });

        res.on('end', () => {
          try {
            const payload = raw ? JSON.parse(raw) : {};
            const isHealthy = statusCode >= 200 && statusCode < 400 && payload && payload.status === 'ok';
            if (isHealthy) {
              resolve(target);
              return;
            }
          } catch (error) {
            // Ignore malformed payloads; they are not valid backend health responses.
          }
          probe();
        });
      });

      req.on('error', () => probe());
      req.setTimeout(500, () => {
        req.destroy();
        probe();
      });
    };

    probe();
  });
}

function isJsonResponse(payload) {
  return payload && typeof payload === 'object' && !Buffer.isBuffer(payload);
}

function buildFallbackPayload(req, status = 'legacy_stub') {
  return {
    status,
    service: 'ifspstory-node',
    path: req.originalUrl,
    message: 'Node/Express API layer is active. The legacy Python IFSP service is not running, so this request is using compatibility fallback behavior.',
    api_contract: 'IFSP legacy compatibility',
    timestamp: new Date().toISOString(),
  };
}

function doRequest(targetUrl, method, body) {
  return new Promise((resolve, reject) => {
    const client = targetUrl.startsWith('https') ? https : http;
    const url = new URL(targetUrl);
    const payload = body && typeof body !== 'string' ? JSON.stringify(body) : body || '';

    const request = client.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload || ''),
        },
      },
      (response) => {
        let raw = '';
        response.on('data', (chunk) => {
          raw += chunk;
        });
        response.on('end', () => {
          try {
            const parsed = raw ? JSON.parse(raw) : {};
            resolve({
              status: response.statusCode || 200,
              payload: parsed,
              raw,
            });
          } catch (error) {
            resolve({
              status: response.statusCode || 200,
              payload: raw,
              raw,
            });
          }
        });
      },
    );

    request.on('error', reject);
    if (payload) {
      request.write(payload);
    }
    request.end();
  });
}

async function proxyToPython(req, res) {
  try {
    const activeBaseUrl = await resolvePythonBaseUrl();
    const targetUrl = `${activeBaseUrl}${req.originalUrl}`;
    const response = await doRequest(targetUrl, req.method, req.body);

    if (response.status >= 400) {
      return res.status(response.status).json({
        ...buildFallbackPayload(req, 'proxy_error'),
        python_status: response.status,
        python_response: response.payload,
      });
    }

    if (isJsonResponse(response.payload)) {
      return res.status(response.status).json(response.payload);
    }

    return res.status(response.status).json({
      data: response.payload,
      service: 'ifspstory-node',
      proxied_to: activeBaseUrl,
    });
  } catch (error) {
    return res.status(200).json(buildFallbackPayload(req, 'legacy_python_unavailable'));
  }
}

module.exports = { proxyToPython, buildFallbackPayload, resolvePythonBaseUrl };

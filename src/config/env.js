const dotenv = require('dotenv');

dotenv.config();

const parseGroupIds = (value) =>
  String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const normalizeLocalhost = (value) =>
  String(value || '')
    .trim()
    .replace('http://127.0.0.1', 'http://localhost')
    .replace('https://127.0.0.1', 'https://localhost')
    .replace('http://localhost.localdomain', 'http://localhost')
    .replace('https://localhost.localdomain', 'https://localhost');

module.exports = {
  port: Number(process.env.PORT || 3004),
  host: process.env.HOST || '0.0.0.0',
  nodeEnv: process.env.NODE_ENV || 'development',
  appName: process.env.APP_NAME || 'IFSP Story',
  pythonBaseUrl: normalizeLocalhost(process.env.PYTHON_BASE_URL || 'http://localhost:8001'),
  logLevel: process.env.LOG_LEVEL || 'info',
  backendPortCandidates: [8000, 8001, 8002, 8003, 8010, 8011],
  tenantId: process.env.AZURE_TENANT_ID || '',
  clientId: process.env.AZURE_CLIENT_ID || '',
  clientSecret: process.env.AZURE_CLIENT_SECRET || '',
  redirectUri: normalizeLocalhost(process.env.AZURE_REDIRECT_URI || 'http://localhost:3004/auth/callback'),
  groupIds: parseGroupIds(process.env.AZURE_GROUP_IDS),
  requireGroupCheck: String(process.env.AZURE_REQUIRE_GROUP_CHECK ?? 'false').toLowerCase() === 'true',
  requiredAppRole: String(process.env.AZURE_REQUIRED_APP_ROLE || '').trim(),
};

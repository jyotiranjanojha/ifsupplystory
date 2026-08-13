const dotenv = require('dotenv');

dotenv.config();

module.exports = {
  port: Number(process.env.PORT || 3000),
  host: process.env.HOST || '0.0.0.0',
  nodeEnv: process.env.NODE_ENV || 'development',
  appName: process.env.APP_NAME || 'IFSP Story',
  pythonBaseUrl: process.env.PYTHON_BASE_URL || 'http://127.0.0.1:8000',
  logLevel: process.env.LOG_LEVEL || 'info',
  backendPortCandidates: [8000, 8001, 8002, 8003, 8010, 8011],
};

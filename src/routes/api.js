const express = require('express');
const { proxyToPython } = require('../services/pythonProxy');

const router = express.Router();

const apiRoutes = [
  ['GET', '/api/auth/me'],
  ['GET', '/api/context/current'],
  ['POST', '/api/context/reset'],
  ['POST', '/api/context/resolve'],
  ['GET', '/api/datasets/summary'],
  ['GET', '/api/llm/models'],
  ['GET', '/api/rag/status'],
  ['POST', '/api/rag/reindex'],
  ['POST', '/api/rag/query'],
  ['POST', '/api/semantic/debug'],
  ['GET', '/api/rag/openvino/status'],
  ['POST', '/api/rag/openvino/export-embedding'],
  ['POST', '/api/rag/openvino/export-reranker'],
  ['POST', '/api/rag/openvino/reindex'],
  ['POST', '/api/rag/openvino/query'],
  ['POST', '/api/validate'],
  ['POST', '/api/validate/report/html'],
  ['POST', '/api/validate/report/email'],
  ['GET', '/api/email/smtp/health'],
  ['POST', '/api/compare'],
  ['POST', '/api/root-cause'],
  ['POST', '/api/insights'],
  ['POST', '/api/knowledge-graph'],
  ['POST', '/api/bom-drill'],
  ['POST', '/api/sql-query'],
  ['POST', '/api/vision-query'],
  ['POST', '/api/chat'],
  ['POST', '/api/chat/stream'],
];

for (const [method, path] of apiRoutes) {
  router[method.toLowerCase()](path, (req, res) => proxyToPython(req, res));
}

module.exports = router;

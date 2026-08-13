const express = require('express');
const { proxyToPython } = require('../services/pythonProxy');

const router = express.Router();

router.get('/api/auth/me', (req, res) => proxyToPython(req, res));
router.get('/api/context/current', (req, res) => proxyToPython(req, res));
router.post('/api/context/reset', (req, res) => proxyToPython(req, res));
router.post('/api/context/resolve', (req, res) => proxyToPython(req, res));
router.get('/api/datasets/summary', (req, res) => proxyToPython(req, res));
router.get('/api/llm/models', (req, res) => proxyToPython(req, res));
router.get('/api/rag/status', (req, res) => proxyToPython(req, res));
router.post('/api/rag/reindex', (req, res) => proxyToPython(req, res));
router.post('/api/rag/query', (req, res) => proxyToPython(req, res));
router.post('/api/semantic/debug', (req, res) => proxyToPython(req, res));
router.get('/api/rag/openvino/status', (req, res) => proxyToPython(req, res));
router.post('/api/rag/openvino/export-embedding', (req, res) => proxyToPython(req, res));
router.post('/api/rag/openvino/export-reranker', (req, res) => proxyToPython(req, res));
router.post('/api/rag/openvino/reindex', (req, res) => proxyToPython(req, res));
router.post('/api/rag/openvino/query', (req, res) => proxyToPython(req, res));

router.post('/api/validate', (req, res) => proxyToPython(req, res));
router.post('/api/validate/report/html', (req, res) => proxyToPython(req, res));
router.post('/api/validate/report/email', (req, res) => proxyToPython(req, res));
router.get('/api/email/smtp/health', (req, res) => proxyToPython(req, res));

router.post('/api/compare', (req, res) => proxyToPython(req, res));
router.post('/api/root-cause', (req, res) => proxyToPython(req, res));
router.post('/api/insights', (req, res) => proxyToPython(req, res));
router.post('/api/knowledge-graph', (req, res) => proxyToPython(req, res));
router.post('/api/bom-drill', (req, res) => proxyToPython(req, res));
router.post('/api/sql-query', (req, res) => proxyToPython(req, res));
router.post('/api/vision-query', (req, res) => proxyToPython(req, res));
router.post('/api/chat', (req, res) => proxyToPython(req, res));
router.post('/api/chat/stream', (req, res) => proxyToPython(req, res));

module.exports = router;

const express = require('express');
const { proxyToPython } = require('../services/pythonProxy');

const router = express.Router();

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

module.exports = router;

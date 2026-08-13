const express = require('express');
const { proxyToPython } = require('../services/pythonProxy');

const router = express.Router();

router.post('/api/chat', (req, res) => proxyToPython(req, res));
router.post('/api/chat/stream', (req, res) => proxyToPython(req, res));

module.exports = router;

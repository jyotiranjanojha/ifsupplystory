const express = require('express');

const router = express.Router();

router.get('/health', (_req, res) => {
  res.status(200).json({
    status: 'ok',
    service: 'ifspstory-node',
    environment: process.env.NODE_ENV || 'development',
    timestamp: new Date().toISOString(),
  });
});

router.get('/api/health', (_req, res) => {
  res.status(200).json({
    status: 'ok',
    service: 'ifspstory-node',
    base_dir: process.cwd(),
  });
});

router.get('/api/config', (_req, res) => {
  res.status(200).json({
    semantic_mode: process.env.SEMANTIC_MODE || 'deterministic',
    allowed_semantic_modes: ['deterministic', 'hybrid', 'llm'],
    semantic_mode_validation: 'ok',
    guidance: 'Node/Express migration is active. Configure env values as needed for deployment.',
  });
});

module.exports = router;

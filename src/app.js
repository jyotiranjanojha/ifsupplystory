const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const healthRoutes = require('./routes/health');
const planningRoutes = require('./routes/planning');
const analysisRoutes = require('./routes/analysis');
const chatRoutes = require('./routes/chat');
const { appName, logLevel } = require('./config/env');

const app = express();

app.use(cors());
app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(morgan(logLevel === 'debug' ? 'dev' : 'combined'));

app.get('/', (_req, res) => {
  res.status(200).json({
    app: appName,
    message: 'Node/Express migration is active.',
    endpoints: ['/health', '/api/health', '/api/config'],
  });
});

app.use(healthRoutes);
app.use(planningRoutes);
app.use(analysisRoutes);
app.use(chatRoutes);

app.use((req, res) => {
  res.status(404).json({
    error: 'Not found',
    path: req.originalUrl,
    service: 'ifspstory-node',
  });
});

module.exports = app;

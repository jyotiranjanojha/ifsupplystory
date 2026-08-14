const app = require('./app');
const { port, host, pythonBaseUrl } = require('./config/env');

function startServer() {
  const server = app.listen(port, host, () => {
    console.log(`IFSP Story API running on http://localhost:${port}`);
    console.log(`Python compatibility target: ${pythonBaseUrl}`);
  });

  server.on('error', (error) => {
    if (error.code === 'EADDRINUSE') {
      console.error(`Port ${port} is already in use. Stop the old IFSP process or change PORT in .env.`);
      process.exit(1);
    }

    console.error('Failed to start IFSP Story API:', error);
    process.exit(1);
  });
}

startServer();

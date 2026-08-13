const app = require('./app');
const { port, host, pythonBaseUrl } = require('./config/env');

function listenOnPort(portNumber) {
  return new Promise((resolve, reject) => {
    const server = app.listen(portNumber, host, () => {
      console.log(`IFSP Story API running on http://localhost:${portNumber}`);
      console.log(`Python compatibility target: ${pythonBaseUrl}`);
      resolve(server);
    });

    server.on('error', (error) => {
      if (error.code === 'EADDRINUSE') {
        return resolve(listenOnPort(portNumber + 1));
      }
      reject(error);
    });
  });
}

listenOnPort(port).catch((error) => {
  console.error('Failed to start IFSP Story API:', error);
  process.exit(1);
});

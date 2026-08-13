const { spawn } = require('child_process');
const path = require('path');

function parseArgs(argv) {
  const args = { host: '127.0.0.1', port: 8000, reload: false, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const current = argv[i];
    if (current === '--host') args.host = argv[i + 1] || args.host;
    if (current === '--port') args.port = Number(argv[i + 1] || args.port);
    if (current === '--reload') args.reload = true;
    if (current === '--help' || current === '-h') args.help = true;
    if (current === '--max-tries') args.maxTries = Number(argv[i + 1] || 30);
  }
  return args;
}

function getPythonCommand() {
  return process.platform === 'win32' ? 'python' : 'python3';
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const repoRoot = __dirname;

  if (options.help) {
    console.log('Usage: node server.js [--host 127.0.0.1] [--port 8000] [--reload] [--max-tries 30]');
    console.log('This launcher starts the existing Python/FastAPI IFSP application with a Node-based entrypoint.');
    return;
  }

  const extraArgs = [];
  if (options.host) extraArgs.push('--host', options.host);
  if (options.port) extraArgs.push('--port', String(options.port));
  if (options.reload) extraArgs.push('--reload');
  if (options.maxTries) extraArgs.push('--max-tries', String(options.maxTries));

  const python = getPythonCommand();
  const child = spawn(python, [path.join(repoRoot, 'webapp', 'run.py'), ...extraArgs], {
    cwd: repoRoot,
    env: process.env,
    stdio: 'inherit',
    shell: false,
  });

  child.on('exit', (code, signal) => {
    if (signal) {
      console.error(`Python app exited due to signal: ${signal}`);
      process.exit(1);
    }
    process.exit(code ?? 0);
  });

  child.on('error', (error) => {
    console.error(`Failed to start Python app: ${error.message}`);
    console.error(`Try installing Python or ensure the command '${python}' is available on PATH.`);
    process.exit(1);
  });
}

main();

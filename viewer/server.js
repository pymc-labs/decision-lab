const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 8080;
const SESSION_DIR = path.join(__dirname, 'demo-session');

app.use(express.static(path.join(__dirname, 'public')));

// API: Get session manifest
app.get('/api/session', (req, res) => {
  const manifest = JSON.parse(fs.readFileSync(path.join(SESSION_DIR, 'session_manifest.json'), 'utf-8'));
  res.json(manifest);
});

// API: Get artifact content
app.get('/api/artifact/*', (req, res) => {
  const artifactPath = req.params[0];
  const fullPath = path.join(SESSION_DIR, artifactPath);

  // Prevent path traversal
  if (!fullPath.startsWith(SESSION_DIR)) {
    return res.status(403).json({ error: 'Access denied' });
  }

  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'Artifact not found' });
  }

  const content = fs.readFileSync(fullPath, 'utf-8');
  const ext = path.extname(artifactPath);

  if (ext === '.json') {
    res.json(JSON.parse(content));
  } else {
    res.type('text/plain').send(content);
  }
});

// API: List all artifacts in session
app.get('/api/artifacts', (req, res) => {
  const artifacts = [];

  function walk(dir, prefix = '') {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const relPath = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.') && entry.name !== 'data') {
          walk(path.join(dir, entry.name), relPath);
        }
      } else if (!entry.name.startsWith('.')) {
        const ext = path.extname(entry.name);
        artifacts.push({
          path: relPath,
          name: entry.name,
          type: ext === '.json' ? 'json' : ext === '.md' ? 'markdown' : ext === '.csv' ? 'csv' : 'text',
          size: fs.statSync(path.join(dir, entry.name)).size
        });
      }
    }
  }

  walk(SESSION_DIR);
  res.json(artifacts);
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Decision Lab Viewer running at http://localhost:${PORT}`);
});

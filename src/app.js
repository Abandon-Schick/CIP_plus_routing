const express = require('express');
const projectRoutes = require('./routes/projects');

function createApp() {
  const app = express();

  app.use(express.json());

  app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  app.use('/api/projects', projectRoutes);

  return app;
}

module.exports = createApp;

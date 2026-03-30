jest.mock('../../src/database', () => {
  let db;
  return {
    getDatabase: () => {
      if (!db) {
        const Sqlite = require('better-sqlite3');
        db = new Sqlite(':memory:');
        db.exec(`
          CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
          )
        `);
        db.exec(`
          CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            department TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
          )
        `);
      }
      return db;
    },
    closeDatabase: () => {
      if (db) { db.close(); db = null; }
    },
  };
});

const request = require('supertest');
const createApp = require('../../src/app');
const { closeDatabase } = require('../../src/database');

describe('API Integration Tests', () => {
  let app;

  beforeAll(() => {
    app = createApp();
  });

  afterAll(() => {
    closeDatabase();
  });

  test('GET /health returns ok', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
  });

  test('POST /api/projects creates a project', async () => {
    const res = await request(app)
      .post('/api/projects')
      .send({ name: 'Bridge Renovation', description: 'Main St bridge repair' });
    expect(res.status).toBe(201);
    expect(res.body.name).toBe('Bridge Renovation');
  });

  test('GET /api/projects lists projects', async () => {
    const res = await request(app).get('/api/projects');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
  });

  test('POST /api/projects without name returns 400', async () => {
    const res = await request(app)
      .post('/api/projects')
      .send({ description: 'Missing name' });
    expect(res.status).toBe(400);
  });

  test('POST /api/projects/:id/routes adds a route', async () => {
    const proj = await request(app)
      .post('/api/projects')
      .send({ name: 'Route Test Project' });

    const res = await request(app)
      .post(`/api/projects/${proj.body.id}/routes`)
      .send({ stepOrder: 1, department: 'Engineering' });
    expect(res.status).toBe(201);
    expect(res.body.department).toBe('Engineering');
  });

  test('GET /api/projects/:id/routes lists routes', async () => {
    const proj = await request(app)
      .post('/api/projects')
      .send({ name: 'Route List Project' });

    await request(app)
      .post(`/api/projects/${proj.body.id}/routes`)
      .send({ stepOrder: 1, department: 'Planning' });

    const res = await request(app).get(`/api/projects/${proj.body.id}/routes`);
    expect(res.status).toBe(200);
    expect(res.body.length).toBeGreaterThanOrEqual(1);
  });
});

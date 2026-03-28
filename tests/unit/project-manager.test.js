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

const ProjectManager = require('../../src/modules/project-manager');
const { closeDatabase } = require('../../src/database');

describe('ProjectManager', () => {
  let pm;

  beforeAll(() => {
    pm = new ProjectManager();
  });

  afterAll(() => {
    closeDatabase();
  });

  test('creates a project', () => {
    const project = pm.createProject({ name: 'Test Project', description: 'A test' });
    expect(project).toBeDefined();
    expect(project.name).toBe('Test Project');
    expect(project.status).toBe('pending');
  });

  test('lists all projects', () => {
    const projects = pm.getAllProjects();
    expect(projects.length).toBeGreaterThanOrEqual(1);
  });

  test('gets project by id', () => {
    const created = pm.createProject({ name: 'Lookup Test' });
    const found = pm.getProjectById(created.id);
    expect(found.name).toBe('Lookup Test');
  });

  test('updates a project', () => {
    const created = pm.createProject({ name: 'Update Me' });
    const updated = pm.updateProject(created.id, { status: 'active' });
    expect(updated.status).toBe('active');
  });

  test('deletes a project', () => {
    const created = pm.createProject({ name: 'Delete Me' });
    const deleted = pm.deleteProject(created.id);
    expect(deleted).toBe(true);
    expect(pm.getProjectById(created.id)).toBeUndefined();
  });

  test('returns null when updating non-existent project', () => {
    const result = pm.updateProject(99999, { name: 'Ghost' });
    expect(result).toBeNull();
  });
});

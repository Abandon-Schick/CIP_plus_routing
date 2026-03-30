const { getDatabase } = require('../database');

class ProjectManager {
  getAllProjects() {
    const db = getDatabase();
    return db.prepare('SELECT * FROM projects ORDER BY created_at DESC').all();
  }

  getProjectById(id) {
    const db = getDatabase();
    return db.prepare('SELECT * FROM projects WHERE id = ?').get(id);
  }

  createProject({ name, description, status, priority }) {
    const db = getDatabase();
    const result = db.prepare(
      'INSERT INTO projects (name, description, status, priority) VALUES (?, ?, ?, ?)'
    ).run(name, description || null, status || 'pending', priority || 'medium');
    return this.getProjectById(result.lastInsertRowid);
  }

  updateProject(id, { name, description, status, priority }) {
    const db = getDatabase();
    const existing = this.getProjectById(id);
    if (!existing) return null;

    db.prepare(
      `UPDATE projects SET name = ?, description = ?, status = ?, priority = ?, updated_at = datetime('now') WHERE id = ?`
    ).run(
      name || existing.name,
      description !== undefined ? description : existing.description,
      status || existing.status,
      priority || existing.priority,
      id
    );
    return this.getProjectById(id);
  }

  deleteProject(id) {
    const db = getDatabase();
    const result = db.prepare('DELETE FROM projects WHERE id = ?').run(id);
    return result.changes > 0;
  }
}

module.exports = ProjectManager;

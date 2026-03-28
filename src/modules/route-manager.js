const { getDatabase } = require('../database');

class RouteManager {
  getRoutesByProject(projectId) {
    const db = getDatabase();
    return db.prepare(
      'SELECT * FROM routes WHERE project_id = ? ORDER BY step_order ASC'
    ).all(projectId);
  }

  addRoute(projectId, { stepOrder, department, notes }) {
    const db = getDatabase();
    const result = db.prepare(
      'INSERT INTO routes (project_id, step_order, department, notes) VALUES (?, ?, ?, ?)'
    ).run(projectId, stepOrder, department, notes || null);
    return db.prepare('SELECT * FROM routes WHERE id = ?').get(result.lastInsertRowid);
  }

  updateRouteStatus(routeId, status) {
    const db = getDatabase();
    db.prepare('UPDATE routes SET status = ? WHERE id = ?').run(status, routeId);
    return db.prepare('SELECT * FROM routes WHERE id = ?').get(routeId);
  }

  deleteRoute(routeId) {
    const db = getDatabase();
    const result = db.prepare('DELETE FROM routes WHERE id = ?').run(routeId);
    return result.changes > 0;
  }
}

module.exports = RouteManager;

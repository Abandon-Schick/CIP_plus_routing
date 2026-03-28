const { Router } = require('express');
const ProjectManager = require('../modules/project-manager');
const RouteManager = require('../modules/route-manager');

const router = Router();
const projectManager = new ProjectManager();
const routeManager = new RouteManager();

router.get('/', (req, res) => {
  const projects = projectManager.getAllProjects();
  res.json(projects);
});

router.get('/:id', (req, res) => {
  const project = projectManager.getProjectById(req.params.id);
  if (!project) return res.status(404).json({ error: 'Project not found' });
  res.json(project);
});

router.post('/', (req, res) => {
  const { name, description, status, priority } = req.body;
  if (!name) return res.status(400).json({ error: 'Project name is required' });
  const project = projectManager.createProject({ name, description, status, priority });
  res.status(201).json(project);
});

router.put('/:id', (req, res) => {
  const project = projectManager.updateProject(req.params.id, req.body);
  if (!project) return res.status(404).json({ error: 'Project not found' });
  res.json(project);
});

router.delete('/:id', (req, res) => {
  const deleted = projectManager.deleteProject(req.params.id);
  if (!deleted) return res.status(404).json({ error: 'Project not found' });
  res.status(204).send();
});

router.get('/:id/routes', (req, res) => {
  const routes = routeManager.getRoutesByProject(req.params.id);
  res.json(routes);
});

router.post('/:id/routes', (req, res) => {
  const project = projectManager.getProjectById(req.params.id);
  if (!project) return res.status(404).json({ error: 'Project not found' });

  const { stepOrder, department, notes } = req.body;
  if (!department) return res.status(400).json({ error: 'Department is required' });

  const route = routeManager.addRoute(req.params.id, {
    stepOrder: stepOrder || 1,
    department,
    notes,
  });
  res.status(201).json(route);
});

router.patch('/routes/:routeId/status', (req, res) => {
  const { status } = req.body;
  if (!status) return res.status(400).json({ error: 'Status is required' });

  const route = routeManager.updateRouteStatus(req.params.routeId, status);
  if (!route) return res.status(404).json({ error: 'Route not found' });
  res.json(route);
});

module.exports = router;

class TaskProgressController {
  constructor() {
    this._tasks = {}; // { incident_id: { ... } }
    this._interval = null;
    this._panel = null;
  }

  attach() {
    if (this._interval) return;
    this._interval = setInterval(() => this._poll(), 3000);
    this._createPanel();
    document.addEventListener("dfr:dispatch", (e) => this._startTask(e.detail));
  }

  _createPanel() {
    if (document.getElementById("task-progress-panel")) return;
    const panel = document.createElement("div");
    panel.id = "task-progress-panel";
    panel.className = "task-progress-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="task-progress-header">
        <span class="task-progress-title">Task Progress</span>
        <button class="task-progress-close" id="task-progress-close">&times;</button>
      </div>
      <div id="task-progress-content"></div>
    `;
    document.body.appendChild(panel);
    document.getElementById("task-progress-close").addEventListener("click", () => {
      panel.hidden = true;
    });
    this._panel = panel;
  }

  _startTask(detail) {
    const { incident_id, lat, lon } = detail;
    this._tasks[incident_id] = {
      incident_id,
      lat,
      lon,
      steps: [
        { key: "task_created", label: "Task Created", done: true },
        { key: "drone_launching", label: "Drone Launching", done: false },
        { key: "en_route", label: "En Route", done: false },
        { key: "on_scene", label: "On Scene", done: false },
        { key: "completed", label: "Completed", done: false },
      ],
      battery: 100,
      drone_lat: null,
      drone_lon: null,
      started_at: Date.now(),
    };
    this._render();
    this._panel.hidden = false;
    if (window.mapController) {
      window.mapController.drawMissionLine(lat, lon);
    }
  }

  _poll() {
    const ids = Object.keys(this._tasks);
    if (!ids.length) return;
    // In mock mode, simulate progress
    ids.forEach(id => {
      const task = this._tasks[id];
      const elapsed = (Date.now() - task.started_at) / 1000;
      if (elapsed > 5 && !task.steps[1].done) {
        task.steps[1].done = true;
        task.battery = 92;
        this._simulateDroneMove(task, 0.1);
      }
      if (elapsed > 12 && !task.steps[2].done) {
        task.steps[2].done = true;
        task.battery = 78;
        this._simulateDroneMove(task, 0.4);
      }
      if (elapsed > 20 && !task.steps[3].done) {
        task.steps[3].done = true;
        task.battery = 65;
        this._simulateDroneMove(task, 0.7);
      }
      if (elapsed > 30 && !task.steps[4].done) {
        task.steps[4].done = true;
        task.battery = 55;
        this._simulateDroneMove(task, 1.0);
      }
      if (elapsed > 35 && task.steps[4].done) {
        // Cleanup
        if (window.mapController) window.mapController.clearMissionLine();
        delete this._tasks[id];
      }
    });
    this._render();
  }

  _simulateDroneMove(task, fraction) {
    const home = window.mapController?.getLastCoordinates();
    if (!home) return;
    const lat = home.lat + (task.lat - home.lat) * fraction;
    const lon = home.lon + (task.lon - home.lon) * fraction;
    task.drone_lat = lat;
    task.drone_lon = lon;
    if (window.mapController) window.mapController.updateDroneMarker(lat, lon);
  }

  _render() {
    const content = document.getElementById("task-progress-content");
    if (!content) return;
    const ids = Object.keys(this._tasks);
    if (!ids.length) { this._panel.hidden = true; return; }
    const task = this._tasks[ids[0]];
    let html = '<div class="task-battery">&#x1F50B; <span data-i18n="task.battery">Battery</span> ' + task.battery + '%</div>';
    html += '<div class="task-steps">';
    task.steps.forEach((step, i) => {
      const done = step.done;
      const current = !done && (i === 0 || task.steps[i - 1].done);
      const cls = done ? "task-step-done" : current ? "task-step-current" : "task-step-pending";
      const icon = done ? "&#10003;" : current ? "&#9679;" : "&#9675;";
      html += '<div class="task-step ' + cls + '">';
      html += '<span class="task-step-icon">' + icon + '</span>';
      html += '<span class="task-step-label" data-i18n="task.' + step.key + '">' + step.label + '</span>';
      html += '</div>';
      if (i < task.steps.length - 1) {
        html += '<div class="task-step-line ' + (done ? "task-step-line-done" : "") + '"></div>';
      }
    });
    html += '</div>';
    content.innerHTML = html;
    if (window.I18N) window.I18N.apply();
  }
}
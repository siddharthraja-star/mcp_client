require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
const PORT = process.env.UI_PORT || 3000;
const API_URL = process.env.API_URL || "http://localhost:8005";

app.set("view engine", "ejs");
app.set("views", "./views");
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

app.get("/", (req, res) => {
  res.render("index", { apiUrl: API_URL });
});

app.get("/servers", async (req, res) => {
  try {
    const { data } = await axios.get(`${API_URL}/mcp-servers`);
    const rows = Object.entries(data.servers).map(([name, cfg]) => ({
      name,
      command: cfg.command,
      args: (cfg.args || []).join(" "),
      type: cfg.type || "stdio",
      source: cfg._source || "-",
    }));
    res.render("servers", { rows, error: null });
  } catch (err) {
    res.render("servers", { rows: [], error: err.message });
  }
});

app.get("/tools", async (req, res) => {
  const server = req.query.server || "";
  const [serversRes, toolsRes] = await Promise.allSettled([
    axios.get(`${API_URL}/mcp-servers`),
    axios.get(`${API_URL}/list-tools`, { params: server ? { server } : {} }),
  ]);
  const servers = serversRes.status === "fulfilled" ? Object.keys(serversRes.value.data.servers) : [];
  if (toolsRes.status === "fulfilled") {
    const { data } = toolsRes.value;
    res.render("tools", { servers, server: data.server, tools: data.tools, selected: req.query.tool || '', error: null });
  } else {
    res.render("tools", { servers, server, tools: [], selected: '', error: toolsRes.reason.message });
  }
});

async function fetchServersAndTools(server) {
  const [serversRes, toolsRes] = await Promise.allSettled([
    axios.get(`${API_URL}/mcp-servers`),
    axios.get(`${API_URL}/list-tools`, { params: server ? { server } : {} }),
  ]);
  const servers = serversRes.status === "fulfilled" ? Object.keys(serversRes.value.data.servers) : [];
  const tools = toolsRes.status === "fulfilled" ? toolsRes.value.data.tools : [];
  return { servers, tools };
}

// AJAX endpoint used by the frontend to refresh tools on server change
app.get("/api/tools", async (req, res) => {
  try {
    const { data } = await axios.get(`${API_URL}/list-tools`, {
      params: req.query.server ? { server: req.query.server } : {},
    });
    res.json(data.tools);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get("/run-tool", async (req, res) => {
  const server = req.query.server || "";
  const { servers, tools } = await fetchServersAndTools(server);
  res.render("run-tool", { servers, tools, result: null, error: null, form: { server, tool_name: req.query.tool || "" } });
});

app.post("/run-tool", async (req, res) => {
  const { server, tool_name, arguments: rawArgs } = req.body;
  const { servers, tools } = await fetchServersAndTools(server);
  let parsedArgs = {};
  try {
    if (rawArgs && rawArgs.trim()) parsedArgs = JSON.parse(rawArgs);
  } catch {
    return res.render("run-tool", { servers, tools, result: null, error: "Arguments must be valid JSON", form: req.body });
  }
  try {
    const { data } = await axios.post(`${API_URL}/call-tool`, {
      server: server || null,
      tool_name,
      arguments: parsedArgs,
    });
    res.render("run-tool", { servers, tools, result: data, error: null, form: req.body });
  } catch (err) {
    const detail = err.response?.data?.detail || err.message;
    res.render("run-tool", { servers, tools, result: null, error: detail, form: req.body });
  }
});

app.listen(PORT, () => {
  console.log(`InsightStudios MCP Gateway running on http://localhost:${PORT}`);
});

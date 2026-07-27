/**
 * ManuSift pi extension: bridges the Python Domain Kernel (~82 tools,
 * 52 detectors) into the pi agent harness.
 *
 * - Spawns `python -m manusift.toolserver` (JSON-lines stdio bridge)
 * - Registers every domain tool via pi.registerTool() with the JSON
 *   Schema passed through unchanged (pi-ai validates raw JSON Schema)
 * - Installs the ManuSift integrity-screening system prompt
 * - Enforces the legacy ToolCallGate (signature dedup + call caps)
 * - /manusift command: status | restart
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { ToolCallGate } from "./gate";
import { MANUSIFT_SYSTEM_PROMPT } from "./system-prompt";

// .pi/extensions/manusift -> repo root (works from any launch cwd).
const MANUSIFT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

interface ToolSchema {
	name: string;
	description: string;
	input_schema: Record<string, unknown>;
}

interface BridgeResponse {
	id?: number | null;
	ok?: boolean;
	op?: string;
	tools?: ToolSchema[] | number;
	result?: string;
	error?: string;
}

function resolvePython(cwd: string): string {
	const fromEnv = process.env.MANUSIFT_PYTHON;
	if (fromEnv) return fromEnv;
	const winVenv = join(cwd, ".venv", "Scripts", "python.exe");
	if (existsSync(winVenv)) return winVenv;
	const posixVenv = join(cwd, ".venv", "bin", "python");
	if (existsSync(posixVenv)) return posixVenv;
	return process.platform === "win32" ? "python" : "python3";
}

class ToolServerClient {
	private child: ChildProcessWithoutNullStreams | null = null;
	private nextId = 1;
	private pending = new Map<number, { resolve: (r: BridgeResponse) => void; reject: (e: Error) => void }>();
	private readyPromise: Promise<void> | null = null;
	private cwd: string;
	toolCount = 0;

	constructor(cwd: string) {
		this.cwd = cwd;
	}

	get running(): boolean {
		return this.child !== null && this.child.exitCode === null;
	}

	start(): Promise<void> {
		if (this.readyPromise) return this.readyPromise;
		const python = resolvePython(this.cwd);
		const child = spawn(python, ["-m", "manusift.toolserver"], {
			cwd: this.cwd,
			stdio: ["pipe", "pipe", "pipe"],
			env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
		});
		this.child = child;

		// Drain stderr so the pipe never fills; surface lines in debug mode.
		const errRl = createInterface({ input: child.stderr });
		errRl.on("line", (line) => {
			if (process.env.MANUSIFT_TOOLSERVER_DEBUG) {
				console.error(`[manusift-toolserver] ${line}`);
			}
		});

		this.readyPromise = new Promise<void>((resolveReady, rejectReady) => {
			let ready = false;
			const outRl = createInterface({ input: child.stdout });
			outRl.on("line", (line) => {
				let msg: BridgeResponse;
				try {
					msg = JSON.parse(line);
				} catch {
					return;
				}
				if (!ready && msg.op === "ready") {
					ready = true;
					this.toolCount = typeof msg.tools === "number" ? msg.tools : 0;
					resolveReady();
					return;
				}
				const id = typeof msg.id === "number" ? msg.id : null;
				if (id !== null && this.pending.has(id)) {
					const p = this.pending.get(id);
					this.pending.delete(id);
					p?.resolve(msg);
				}
			});
			child.on("error", (err) => {
				if (!ready) rejectReady(err);
				this.failAll(new Error(`toolserver spawn error: ${err.message}`));
			});
			child.on("exit", (code) => {
				if (!ready) rejectReady(new Error(`toolserver exited early (code ${code})`));
				this.failAll(new Error(`toolserver exited (code ${code})`));
				this.child = null;
			});
		});
		return this.readyPromise;
	}

	private failAll(err: Error): void {
		for (const p of this.pending.values()) p.reject(err);
		this.pending.clear();
	}

	private request(payload: Record<string, unknown>): Promise<BridgeResponse> {
		const child = this.child;
		if (!child || child.exitCode !== null) {
			return Promise.reject(new Error("manusift toolserver is not running (try /manusift restart)"));
		}
		const id = this.nextId++;
		return new Promise<BridgeResponse>((resolve, reject) => {
			this.pending.set(id, { resolve, reject });
			child.stdin.write(`${JSON.stringify({ ...payload, id })}\n`, (err) => {
				if (err) {
					this.pending.delete(id);
					reject(err);
				}
			});
		});
	}

	async listTools(): Promise<ToolSchema[]> {
		const resp = await this.request({ op: "list" });
		if (!resp.ok || !Array.isArray(resp.tools)) {
			throw new Error(resp.error ?? "toolserver list failed");
		}
		return resp.tools;
	}

	async callTool(tool: string, input: Record<string, unknown>): Promise<string> {
		const resp = await this.request({ op: "call", tool, input });
		if (!resp.ok) throw new Error(resp.error ?? `tool ${tool} failed`);
		return resp.result ?? "";
	}

	stop(): void {
		const child = this.child;
		this.child = null;
		this.readyPromise = null;
		if (child && child.exitCode === null) {
			try {
				child.stdin.write('{"op":"shutdown"}\n');
			} catch {
				// stdin may already be closed; kill below.
			}
			setTimeout(() => {
				if (child.exitCode === null) child.kill();
			}, 2000).unref();
		}
	}
}

function promptSnippet(description: string): string {
	const firstSentence = description.split(/(?<=\.)\s/, 1)[0] ?? description;
	return firstSentence.length > 100 ? `${firstSentence.slice(0, 97)}...` : firstSentence;
}

export default function manusiftExtension(pi: ExtensionAPI) {
	const root = MANUSIFT_ROOT;
	let client = new ToolServerClient(root);
	const gate = new ToolCallGate();
	const registered = new Set<string>();
	let domainToolNames = new Set<string>();

	const registerDomainTools = async (): Promise<number> => {
		const tools = await client.listTools();
		// Safe mode (standalone agent without --dev): drop execution-capable
		// domain tools to match the read-only built-in surface.
		const unsafe = new Set(["bash", "python_exec", "web_fetch", "web_search"]);
		const allowed =
			process.env.MANUSIFT_AGENT_SAFE === "1" ? tools.filter((t) => !unsafe.has(t.name)) : tools;
		domainToolNames = new Set(allowed.map((t) => t.name));
		for (const tool of allowed) {
			if (registered.has(tool.name)) continue;
			registered.add(tool.name);
			pi.registerTool({
				name: tool.name,
				label: tool.name,
				description: tool.description || tool.name,
				promptSnippet: promptSnippet(tool.description || tool.name),
				parameters: tool.input_schema as never,
				async execute(_toolCallId, params) {
					const input = (params ?? {}) as Record<string, unknown>;
					const result = await client.callTool(tool.name, input);
					gate.record(tool.name, input);
					return { content: [{ type: "text", text: result }], details: {} };
				},
			});
		}
		try {
			const active = pi.getActiveTools();
			pi.setActiveTools([...new Set([...active, ...domainToolNames])]);
		} catch {
			// Older hosts without active-tool management still work.
		}
		return allowed.length;
	};

	const connect = async (notify?: (msg: string, level: "info" | "warning" | "error") => void): Promise<void> => {
		try {
			notify?.("ManuSift: starting Python toolserver (first start may take 10-30s)...", "info");
			await client.start();
			const count = await registerDomainTools();
			notify?.(`ManuSift: ${count} domain tools registered`, "info");
		} catch (err) {
			notify?.(
				`ManuSift toolserver unavailable: ${err instanceof Error ? err.message : String(err)}. ` +
					"Domain tools disabled. Fix Python env (MANUSIFT_PYTHON) and run /manusift restart.",
				"error",
			);
		}
	};

	pi.on("session_start", async (_event, ctx) => {
		await connect((msg, level) => ctx.ui.notify(msg, level));
	});

	pi.on("session_shutdown", async () => {
		client.stop();
	});

	pi.on("before_agent_start", async (event) => {
		// Standalone manusift-agent mode already replaced the prompt.
		if (event.systemPrompt.includes("You are ManuSift")) return;
		return { systemPrompt: `${MANUSIFT_SYSTEM_PROMPT}\n\n---\n\n${event.systemPrompt}` };
	});

	pi.on("turn_start", async () => {
		gate.newTurn();
	});

	pi.on("tool_call", async (event) => {
		if (!domainToolNames.has(event.toolName)) return;
		const denied = gate.check(event.toolName, event.input as Record<string, unknown>);
		if (denied) return { block: true, reason: denied };
	});

	pi.registerCommand("screen", {
		description: "Run the full offline screening pipeline on a PDF: /screen <pdf path>",
		handler: async (args, ctx) => {
			const pdfPath = (args ?? "").trim().replace(/^"|"$/g, "");
			if (!pdfPath) {
				ctx.ui.notify("Usage: /screen <pdf path>", "warning");
				return;
			}
			if (!client.running) {
				ctx.ui.notify("ManuSift toolserver NOT running (/manusift restart)", "error");
				return;
			}
			let jobId: string;
			try {
				const submit = JSON.parse(await client.callTool("submit_screen", { path: pdfPath }));
				jobId = String(submit.job_id ?? "");
				if (!jobId) throw new Error(submit.error ?? "submit_screen returned no job_id");
			} catch (err) {
				ctx.ui.notify(
					`submit_screen failed: ${err instanceof Error ? err.message : String(err)}`,
					"error",
				);
				return;
			}
			ctx.ui.notify(`ManuSift: full-pipeline job ${jobId} submitted; polling...`, "info");
			const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
			let status: { status?: string; progress_pct?: number; current_step?: string } = {};
			for (;;) {
				await sleep(3000);
				try {
					status = JSON.parse(await client.callTool("get_job_status", { job_id: jobId }));
				} catch {
					continue;
				}
				const state = String(status.status ?? "unknown");
				const pct = status.progress_pct ?? 0;
				ctx.ui.setStatus("manusift", `screen ${jobId}: ${state} ${pct}%`);
				if (state === "done" || state === "failed") break;
			}
			ctx.ui.setStatus("manusift", undefined);
			if (String(status.status) === "failed") {
				ctx.ui.notify(`ManuSift screen job ${jobId} failed`, "error");
				return;
			}
			let result: string;
			try {
				result = await client.callTool("get_job_result", { job_id: jobId });
			} catch (err) {
				ctx.ui.notify(
					`get_job_result failed: ${err instanceof Error ? err.message : String(err)}`,
					"error",
				);
				return;
			}
			const MAX = 20000;
			const payload =
				result.length > MAX ? `${result.slice(0, MAX)}\n...[truncated ${result.length - MAX} chars]` : result;
			pi.sendMessage(
				{
					customType: "manusift-screen",
					content:
						`Full-pipeline screen job ${jobId} for ${pdfPath} finished. ` +
						"Summarize the verdict below for the user in the 5-section review shape " +
						"(当前状态 / 已检查 / 关键风险 / 未能测试 / 下一步), in the user's language, " +
						"screening-signals vocabulary only, and mention the report artifact paths.\n\n" +
						payload,
					display: true,
				},
				{ triggerTurn: true },
			);
		},
	});

	pi.registerCommand("manusift", {
		description: "ManuSift bridge: /manusift status | restart",
		handler: async (args, ctx) => {
			const sub = (args ?? "").trim() || "status";
			if (sub === "status") {
				ctx.ui.notify(
					client.running
						? `ManuSift toolserver running; ${registered.size} tools registered`
						: "ManuSift toolserver NOT running (/manusift restart)",
					client.running ? "info" : "warning",
				);
				return;
			}
			if (sub === "restart") {
				client.stop();
				client = new ToolServerClient(root);
				await connect((msg, level) => ctx.ui.notify(msg, level));
				return;
			}
			ctx.ui.notify("Usage: /manusift status | restart", "warning");
		},
	});
}

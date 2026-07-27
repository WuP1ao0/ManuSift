#!/usr/bin/env node
/**
 * ManuSift standalone academic-integrity agent (oh-my-pi style, no fork).
 *
 * Built on the pi coding-agent SDK: full InteractiveMode TUI with
 * ManuSift branding, a replaced system prompt, the Python Domain Kernel
 * bridge extension, and a read-only built-in tool surface by default.
 *
 * Usage:
 *   manusift-agent                 interactive TUI
 *   manusift-agent -p "<prompt>"   one-shot print mode
 *   manusift-agent --dev           full pi coding tool surface (bash/edit/write)
 */

import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
	createAgentSessionFromServices,
	createAgentSessionRuntime,
	createAgentSessionServices,
	getAgentDir,
	InteractiveMode,
	runPrintMode,
	SessionManager,
} from "@earendil-works/pi-coding-agent";
import { MANUSIFT_SYSTEM_PROMPT } from "../src/system-prompt.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

function parseArgs(argv) {
	const args = { print: false, dev: false, help: false, message: undefined };
	const positional = [];
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		if (a === "-p" || a === "--print") args.print = true;
		else if (a === "--dev") args.dev = true;
		else if (a === "-h" || a === "--help") args.help = true;
		else positional.push(a);
	}
	if (positional.length > 0) args.message = positional.join(" ");
	return args;
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
	console.log(
		[
			"ManuSift — academic-integrity screening agent (pi harness)",
			"",
			"Usage:",
			"  manusift-agent                 interactive TUI",
			'  manusift-agent -p "<prompt>"   one-shot print mode',
			"  manusift-agent --dev           enable full coding tools (bash/edit/write)",
			"",
			"Env: MANUSIFT_PYTHON (toolserver python), MANUSIFT_TOOLSERVER_DEBUG=1",
		].join("\n"),
	);
	process.exit(0);
}

const cwd = process.cwd();
const atRoot = resolve(cwd) === ROOT;

const resourceLoaderOptions = {
	systemPromptOverride: () => MANUSIFT_SYSTEM_PROMPT,
	// Always load the bridge + branding; skip the bridge dir when running
	// from the repo root where project discovery already picks it up.
	additionalExtensionPaths: [
		...(atRoot ? [] : [join(ROOT, ".pi", "extensions", "manusift")]),
		join(ROOT, "agent", "src", "branding.ts"),
	],
	additionalSkillPaths: atRoot ? [] : [join(ROOT, ".pi", "skills")],
};

// Integrity screening handles untrusted PDFs: default to a read-only
// built-in surface. Domain tools are activated by the bridge extension,
// which additionally drops bash/python_exec/web_* in safe mode.
const excludeTools = args.dev ? undefined : ["bash", "edit", "write"];
if (!args.dev) process.env.MANUSIFT_AGENT_SAFE = "1";

const createRuntime = async ({ cwd: effectiveCwd, sessionManager, sessionStartEvent }) => {
	const services = await createAgentSessionServices({
		cwd: effectiveCwd,
		resourceLoaderOptions,
	});
	return {
		...(await createAgentSessionFromServices({
			services,
			sessionManager,
			sessionStartEvent,
			excludeTools,
		})),
		services,
		diagnostics: services.diagnostics,
	};
};

const runtime = await createAgentSessionRuntime(createRuntime, {
	cwd,
	agentDir: getAgentDir(),
	sessionManager: args.print ? SessionManager.inMemory(cwd) : SessionManager.create(cwd),
});

if (args.print) {
	if (!args.message) {
		console.error('print mode needs a prompt: manusift-agent -p "..."');
		process.exit(2);
	}
	await runPrintMode(runtime, {
		mode: "text",
		initialMessage: args.message,
		initialImages: [],
		messages: [],
	});
} else {
	const mode = new InteractiveMode(runtime, {
		migratedProviders: [],
		modelFallbackMessage: undefined,
		initialMessage: args.message,
		initialImages: [],
		initialMessages: [],
	});
	await mode.run();
}

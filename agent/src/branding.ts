/**
 * ManuSift branding extension: custom TUI header + footer status.
 * Loaded by agent/bin/manusift-agent.mjs via additionalExtensionPaths.
 */

import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";

function banner(theme: Theme): string[] {
	const accent = (s: string) => theme.fg("accent", s);
	const muted = (s: string) => theme.fg("muted", s);
	const dim = (s: string) => theme.fg("dim", s);
	return [
		"",
		accent("  ███╗   ███╗ █████╗ ███╗   ██╗██╗   ██╗") + muted("  ███████╗██╗███████╗████████╗"),
		accent("  ████╗ ████║██╔══██╗████╗  ██║██║   ██║") + muted("  ██╔════╝██║██╔════╝╚══██╔══╝"),
		accent("  ██╔████╔██║███████║██╔██╗ ██║██║   ██║") + muted("  ███████╗██║█████╗     ██║"),
		accent("  ██║╚██╔╝██║██╔══██║██║╚██╗██║██║   ██║") + muted("  ╚════██║██║██╔══╝     ██║"),
		accent("  ██║ ╚═╝ ██║██║  ██║██║ ╚████║╚██████╔╝") + muted("  ███████║██║██║        ██║"),
		accent("  ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ") + muted("  ╚══════╝╚═╝╚═╝        ╚═╝"),
		"",
		muted("  学术论文诚信纠察 · Academic Integrity Screening Agent"),
		dim("  signals, not verdicts · /screen <pdf> 全管线筛查 · /manusift status 查看桥状态"),
		"",
	];
}

export default function manusiftBranding(pi: ExtensionAPI) {
	pi.on("session_start", async (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		ctx.ui.setHeader((_tui, theme) => ({
			render(_width: number): string[] {
				return banner(theme);
			},
			invalidate() {},
		}));
	});
}

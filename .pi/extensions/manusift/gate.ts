/**
 * Per-session tool-call gate for ManuSift domain tools.
 *
 * Ported from the former Python `manusift/agent/safety.py`
 * (ToolCallGate): exact-signature dedup + per-name / per-turn caps.
 * Applies only to ManuSift domain tools; pi built-ins are governed by
 * pi itself.
 */

export class ToolCallGate {
	maxSameTool: number;
	maxPerTurn: number;
	signaturesCap = 1000;
	exempt = new Set(["render_report"]);
	private calledSignatures = new Map<string, true>();
	private toolCallCounts = new Map<string, number>();
	private turnCallCount = 0;

	constructor(opts?: { maxSameTool?: number; maxPerTurn?: number }) {
		this.maxSameTool = opts?.maxSameTool ?? 12;
		this.maxPerTurn = opts?.maxPerTurn ?? 50;
	}

	newTurn(): void {
		this.turnCallCount = 0;
	}

	private sigKey(name: string, args: Record<string, unknown>): string {
		let argsStr: string;
		try {
			argsStr = JSON.stringify(args, Object.keys(args).sort());
		} catch {
			argsStr = String(args);
		}
		return `${name}|${argsStr}`;
	}

	/** Return a denial message if the call is blocked, else null. */
	check(name: string, args: Record<string, unknown> | undefined): string | null {
		const a = args ?? {};
		const key = this.sigKey(name, a);
		if (this.calledSignatures.has(key)) {
			return (
				`duplicate tool call -- tool '${name}' with the same arguments ` +
				"has already been executed in this conversation. Pick a " +
				"different tool, change the arguments, or write a final summary."
			);
		}
		if (this.maxPerTurn > 0 && this.turnCallCount >= this.maxPerTurn) {
			return (
				`budget_exhausted -- tool calls per turn cap ` +
				`(${this.maxPerTurn}) reached.`
			);
		}
		if (!this.exempt.has(name) && this.maxSameTool > 0) {
			const count = this.toolCallCounts.get(name) ?? 0;
			if (count >= this.maxSameTool) {
				return (
					`budget_exhausted -- tool '${name}' called ${count} times ` +
					`(cap ${this.maxSameTool}).`
				);
			}
		}
		return null;
	}

	record(name: string, args: Record<string, unknown> | undefined): void {
		const key = this.sigKey(name, args ?? {});
		this.calledSignatures.set(key, true);
		while (this.calledSignatures.size > this.signaturesCap) {
			const oldest = this.calledSignatures.keys().next().value;
			if (oldest === undefined) break;
			this.calledSignatures.delete(oldest);
		}
		this.toolCallCounts.set(name, (this.toolCallCounts.get(name) ?? 0) + 1);
		this.turnCallCount += 1;
	}
}

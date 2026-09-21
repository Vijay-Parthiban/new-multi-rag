/**
 * Friendly names and tones for guardrails validator ids.
 *
 * The catalog lives in the guardrails service, so a validator can appear in a trace before this
 * map knows about it. guardMeta() falls back to a readable form of the id, which keeps a new
 * validator from showing up as a raw slug.
 */

export interface GuardMeta {
    title: string;
    tone: string;
}

const GUARD_LABELS: Record<string, GuardMeta> = {
    ban_list: { title: "Banned keyword", tone: "ban" },
    detect_pii: { title: "Personal information", tone: "pii" },
    toxic_language: { title: "Toxic language", tone: "toxic" },
    restrict_to_topic: { title: "Restrict to topic", tone: "scope" },
    prompt_injection: { title: "Prompt injection", tone: "security" },
    secrets_present: { title: "Secrets present", tone: "security" },
    mentions_drugs: { title: "Mentions drugs", tone: "toxic" },
};

/** "secrets_present" reads as "Secrets present" rather than a raw slug. */
export function humanizeGuardId(id: string): string {
    const text = id.replace(/_/g, " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
}

export function guardMeta(id: string | null | undefined): GuardMeta {
    if (!id) return { title: "Unknown guard", tone: "other" };
    return GUARD_LABELS[id] ?? { title: humanizeGuardId(id), tone: "other" };
}

export function guardTitle(id: string | null | undefined): string {
    return guardMeta(id).title;
}

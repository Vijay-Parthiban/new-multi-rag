import { SYNTHETIC_EVOLUTIONS } from "./api";

/**
 * The question types, one list for every page. The generator calls them evolutions; a
 * manual file or the Dataset Validator writes a single `question_type`. Both land in
 * `metadata.evolutions`, so a row reads the same wherever it came from.
 */
export const QUESTION_TYPES: readonly string[] = SYNTHETIC_EVOLUTIONS;

export function rowQuestionTypes(
  metadata: Record<string, unknown> | null | undefined,
): string[] {
  const evolutions = metadata?.evolutions;
  if (Array.isArray(evolutions) && evolutions.length > 0) return evolutions.map(String);
  const type = metadata?.question_type;
  return typeof type === "string" && type.trim() ? [type.trim()] : [];
}

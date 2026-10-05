const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

/** ¿Esta persona es la que se nombró en la reunión ("la Directora", "Laura")? */
export function matchesSuggestion(
  person: { name: string; job_title: string | null },
  suggestion?: string | null,
): boolean {
  if (!suggestion) return false;
  const said = normalize(suggestion);
  const words = (text: string) => normalize(text).split(/\s+/).filter((word) => word.length >= 3);
  const nameHit = words(person.name).some((word) => said.split(/\W+/).includes(word));
  const roleHit = !!person.job_title && words(person.job_title).some((word) => said.includes(word));
  return nameHit || roleHit;
}

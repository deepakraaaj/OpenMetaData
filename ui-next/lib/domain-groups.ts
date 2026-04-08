export function formatDomainGroupLabel(groupKey: string): string {
  const key = (groupKey || "").trim();
  if (!key) return "Unknown";
  if (key.toLowerCase() === "misc") return "Miscellaneous";
  if (/[A-Z]/.test(key) || /[&/() -]/.test(key)) return key;
  return key
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

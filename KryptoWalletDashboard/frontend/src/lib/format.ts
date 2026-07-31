const CHF_FORMATTER = new Intl.NumberFormat("de-CH", {
  style: "currency",
  currency: "CHF",
});

export function formatChf(value: string | null): string {
  if (value === null) {
    return "–";
  }
  return CHF_FORMATTER.format(Number(value));
}

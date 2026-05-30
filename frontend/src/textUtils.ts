export function fixTextEncoding(value: string): string {
  const text = value.trim();
  if (!text) return text;
  if (text.includes("Ã") || text.includes("â€™") || text.includes("á»")) {
    try {
      const bytes = new Uint8Array([...text].map((char) => char.charCodeAt(0) & 0xff));
      const repaired = new TextDecoder("utf-8").decode(bytes);
      if (repaired && !repaired.includes("Ã")) {
        return repaired.trim();
      }
    } catch {
      /* ignore */
    }
  }
  return text;
}

function foldVietnamese(value: string): string {
  return value
    .toLowerCase()
    .replace(/đ/g, "d")
    .replace(/[ăâ]/g, "a")
    .replace(/[ê]/g, "e")
    .replace(/[ôơ]/g, "o")
    .replace(/[ư]/g, "u")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function hasDiacritics(value: string): boolean {
  return /[\u0300-\u036făâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]/i.test(value);
}

export function normalizeLimitations(items: string[]): string[] {
  const cleaned: string[] = [];
  const folds: string[] = [];

  for (const raw of items) {
    const text = fixTextEncoding(raw).replace(/\s+/g, " ").trim();
    if (!text) continue;

    const fold = foldVietnamese(text);
    const existingIndex = folds.findIndex((existingFold) => existingFold === fold);
    if (existingIndex >= 0) {
      if (hasDiacritics(text) && !hasDiacritics(cleaned[existingIndex] ?? "")) {
        cleaned[existingIndex] = text;
      }
      continue;
    }

    folds.push(fold);
    cleaned.push(text);
  }

  return cleaned;
}

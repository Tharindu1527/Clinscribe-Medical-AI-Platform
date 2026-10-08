"""Drug-name lexicon over the graph's drugs: finds which drugs a question or chunk mentions.

Terms per drug: the DDInter name, the RxNorm ingredient name, a salt-free alias ("lithium" for
lithium carbonate; not for electrolytes, where "potassium" usually means the lab value) and RxNorm
brand names. Generic terms match case-insensitively; brand names must be capitalised in the text
("Eliquis", "ELIQUIS"), so a brand that is also an English word does not fire on lower-case prose.
Matching is longest-first over word n-grams, so "insulin glargine" wins over a shorter term.
Substances whose names are everyday clinical words ("glucose" for dextrose, "oxygen") are not
matched: in this corpus they are lab values or physiology far more often than a co-prescribed drug.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
SALTS = frozenset(
    {
        "acetate", "besylate", "bromide", "carbonate", "chloride", "citrate", "fumarate",
        "gluconate", "hydrobromide", "hydrochloride", "hyclate", "maleate", "mesylate", "nitrate",
        "phosphate", "potassium", "sodium", "succinate", "sulfate", "tartrate", "trihydrate",
        "monohydrate", "dihydrate", "calcium", "magnesium", "hcl",
        # ester and prodrug suffixes ("dabigatran etexilate" is asked about as "dabigatran")
        "etexilate", "medoxomil", "axetil", "mofetil", "propionate", "dipropionate", "furoate",
        "xinafoate", "tromethamine", "disodium", "dihydrochloride", "hemihydrate", "pivoxil",
    }
)  # fmt: skip
# Fixed-dose combinations named in clinical text but listed by component in DDInter
COMBINATIONS = {
    "co-trimoxazole": ("sulfamethoxazole", "trimethoprim"),
    "cotrimoxazole": ("sulfamethoxazole", "trimethoprim"),
    "co-amoxiclav": ("amoxicillin", "clavulanic acid"),
}
# A salt-free alias that is one of these words would mostly match lab values, not the drug
ELECTROLYTES = frozenset({"potassium", "sodium", "calcium", "magnesium", "chloride", "phosphate"})
MIN_BRAND_CHARS = 4
# Checked against corpus mention counts (2026-10-08): "glucose" (dextrose) 289 chunks, "oxygen" 121,
# almost all about blood glucose or oxygenation. Drugs that are simply common, such as warfarin
# (479), stay: frequency alone would drop the drugs this corpus is about.
NOT_DRUG_TERMS = frozenset(
    {
        "glucose",
        "dextrose",
        "oxygen",
        "water",
        "air",
        "nitrogen",
        "carbon dioxide",
        "sodium chloride",
    }
)


def tokens(text: str) -> list[str]:
    return _WORD.findall(text)


def salt_free(name: str) -> str | None:
    """'Lithium carbonate' -> 'lithium'; None when nothing is stripped or the rest is unusable."""
    words = name.lower().split()
    kept = [w for w in words if w not in SALTS]
    if not kept or len(kept) == len(words):
        return None
    alias = " ".join(kept)
    if alias in ELECTROLYTES or len(alias) < 4:
        return None
    return alias


class DrugLexicon:
    def __init__(self, drugs: Iterable[Mapping[str, Any]]) -> None:
        self.names: dict[str, str] = {}
        self.identity: dict[str, str] = {}  # key -> one id per ingredient (formulations merge)
        self._generic: dict[tuple[str, ...], set[str]] = {}
        self._brand: dict[tuple[str, ...], set[str]] = {}
        for drug in drugs:
            key = str(drug["ddinter_id"])
            self.names[key] = str(drug["name"])
            base = str(drug["name"]).split(" (")[0].lower()  # "Budesonide (nasal)" -> budesonide
            self.identity[key] = str(drug.get("rxcui") or base)
            generic = {str(drug["name"]).lower()}
            if drug.get("ingredient"):
                generic.add(str(drug["ingredient"]).lower())
            generic |= {a for a in (salt_free(t) for t in list(generic)) if a}
            for term in generic - NOT_DRUG_TERMS:
                self._generic.setdefault(tuple(t.lower() for t in tokens(term)), set()).add(key)
            for brand in drug.get("brands") or []:
                if len(brand) >= MIN_BRAND_CHARS and brand.lower() not in NOT_DRUG_TERMS:
                    self._brand.setdefault(tuple(t.lower() for t in tokens(brand)), set()).add(key)
        for combination, parts in COMBINATIONS.items():
            keys = set().union(*(self._generic.get(tuple(tokens(p)), set()) for p in parts))
            if keys:
                self._generic[tuple(tokens(combination))] = keys
        lengths = [len(t) for t in [*self._generic, *self._brand]]
        self._longest = max(lengths, default=1)

    def distinct(self, keys: Iterable[str]) -> int:
        """How many different drugs the keys stand for (formulations of a drug count once)."""
        return len({self.identity.get(k, k) for k in keys})

    def find(self, text: str) -> set[str]:
        """Keys of all drugs mentioned in the text."""
        words = tokens(text)
        lower = [w.lower() for w in words]
        found: set[str] = set()
        i = 0
        while i < len(words):
            for n in range(min(self._longest, len(words) - i), 0, -1):
                gram = tuple(lower[i : i + n])
                keys = set(self._generic.get(gram, ()))
                if gram in self._brand and words[i][:1].isupper():
                    keys |= self._brand[gram]
                if keys:
                    found |= keys
                    i += n
                    break
            else:
                i += 1
        return found

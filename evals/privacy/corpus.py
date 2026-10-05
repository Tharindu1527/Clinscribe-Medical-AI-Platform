"""Seeded synthetic clinical snippets with fake PHI and ground-truth labels.

Every identifier comes from Faker with a fixed seed: no real patient data (CLAUDE.md rule 1).
Each snippet records the PHI values it contains, so evaluations can check whether any survive.
"""

import random
import string
from dataclasses import dataclass, field

from faker import Faker

# Types with an exact format: the gate requires recall 1.0 for these
STRUCTURED = (
    "DATE",
    "AGE_OVER_89",
    "PHONE",
    "EMAIL",
    "SSN",
    "MRN",
    "HEALTH_PLAN_ID",
    "ACCOUNT_NUMBER",
    "LICENSE_NUMBER",
    "VEHICLE_ID",
    "DEVICE_ID",
    "URL",
    "IP_ADDRESS",
    "STREET_ADDRESS",
    "ZIP",
)
# NER types: recall is recorded as the baseline for the Phase 5 fine-tuned model
NER = ("PERSON", "LOCATION")

TEMPLATES = [
    "{PERSON} (MRN {MRN}) was seen on {DATE} for chest pain lasting 3 days. Call back at {PHONE}.",
    "Patient {PERSON}, DOB {DATE}, lives at {STREET_ADDRESS}, {LOCATION}, MA {ZIP}.",
    "Insurance member ID {HEALTH_PLAN_ID}; billing account number {ACCOUNT_NUMBER}. Email {EMAIL}.",
    "SSN on file {SSN}. Pacemaker serial number {DEVICE_ID} checked, no alerts.",
    "A {AGE_OVER_89}-year-old woman presents with confusion. Daughter {PERSON} at bedside.",
    "Drove here himself; vehicle VIN {VEHICLE_ID}. Driver license number {LICENSE_NUMBER}.",
    "Patient portal {URL} accessed from {IP_ADDRESS} on {DATE}. Take 2 tablets twice daily.",
    "Referred by Dr. {PERSON} from {LOCATION}. Fax results to {PHONE}. Next visit {DATE}.",
    "Mr. {PERSON} reports BP 142/88 and HbA1c 7.9% since {DATE}. Contact: {EMAIL}.",
    "Emergency contact {PERSON}, {PHONE}, {STREET_ADDRESS}, {LOCATION}, NY {ZIP}.",
]


@dataclass(frozen=True)
class Snippet:
    text: str
    phi: list[tuple[str, str]] = field(default_factory=list)  # (entity type, value)


def _value(fake: Faker, rng: random.Random, entity: str) -> str:
    upper = string.ascii_uppercase + string.digits
    makers = {
        "PERSON": lambda: fake.name(),
        "LOCATION": lambda: fake.city(),
        "DATE": lambda: fake.date_of_birth().strftime(
            rng.choice(["%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%d %b %Y"])
        ),
        "AGE_OVER_89": lambda: str(rng.randint(90, 104)),
        "PHONE": lambda: (
            rng.choice(
                [
                    fake.numerify("(###) ###-####"),
                    fake.numerify("###-###-####"),
                    fake.numerify("###.###.####"),
                    fake.numerify("+1-###-###-####x###"),
                ]
            )
            .replace("(0", "(2")
            .replace("(1", "(3")
        ),
        "EMAIL": lambda: fake.email(),
        "SSN": lambda: fake.ssn(),
        "MRN": lambda: fake.numerify("########"),
        "HEALTH_PLAN_ID": lambda: "".join(rng.choices(upper, k=10)),
        "ACCOUNT_NUMBER": lambda: fake.numerify("##########"),
        "LICENSE_NUMBER": lambda: fake.bothify("?#######").upper(),
        "VEHICLE_ID": lambda: "".join(rng.choices("ABCDEFGHJKLMNPRSTUVWXYZ0123456789", k=17)),
        "DEVICE_ID": lambda: fake.bothify("SN-####-????").upper(),
        "URL": lambda: f"https://portal.{fake.domain_name()}/patient/{fake.numerify('#####')}",
        "IP_ADDRESS": lambda: fake.ipv4_public(),
        "STREET_ADDRESS": lambda: fake.street_address(),
        "ZIP": lambda: fake.zipcode(),
    }
    return makers[entity]()


def build(n: int = 200, seed: int = 42) -> list[Snippet]:
    fake = Faker("en_US")
    Faker.seed(seed)
    rng = random.Random(seed)
    snippets = []
    for i in range(n):
        template = TEMPLATES[i % len(TEMPLATES)]
        phi: list[tuple[str, str]] = []
        text = template
        while "{" in text:
            start = text.index("{")
            end = text.index("}", start)
            entity = text[start + 1 : end]
            value = _value(fake, rng, entity)
            phi.append((entity, value))
            text = text[:start] + value + text[end + 1 :]
        snippets.append(Snippet(text, phi))
    return snippets

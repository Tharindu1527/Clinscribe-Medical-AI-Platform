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


# Held out: written after de-ID v1 was tuned on TEMPLATES and never used to design recognisers.
# Phrasings v1 has no cue for on purpose (neighbour, family meeting, sentence-initial names, two
# places, "Dr" without a period), so this set measures generalisation, not memorisation.
HELDOUT_TEMPLATES = [
    "I saw {PERSON} today; she was brought in by her son {PERSON} after a fall.",
    "Her neighbour {PERSON} found her on the kitchen floor this morning.",
    "Plan discussed with {PERSON} and {PERSON} at the family meeting.",
    "{PERSON} is a retired teacher originally from {LOCATION}, now living near {LOCATION}.",
    "Spoke with {PERSON} by phone on {PHONE} about the biopsy result.",
    "Discussed with Dr {PERSON} on call; transfer to {LOCATION} declined.",
    "Letters go to {STREET_ADDRESS}, {LOCATION}, CA {ZIP}; copy to {EMAIL}.",
    "{PERSON} works as a nurse in {LOCATION} and cares for her mother.",
    "Seen with interpreter {PERSON}; family recently moved here from {LOCATION}.",
    "Pharmacy called {PERSON} at {PHONE} on {DATE} about the warfarin dose.",
]


# Held-out v2 (2026-10-19), written before the LoRA name/place tagger was first run: the tagger's
# training phrasings (finetune/make_dataset.py) were designed after seeing held-out v1's misses
# ("originally from", "works in"), so v1 would flatter it. Speech-like, with and without cues.
HELDOUT_V2_TEMPLATES = [
    "Okay so {PERSON} rang this morning, she's been staying with family in {LOCATION}.",
    "Can you send a copy of the letter to {PERSON} at the practice in {LOCATION}?",
    "He declined the flu jab again; his wife {PERSON} will talk to him about it.",
    "The ambulance took him from {LOCATION} straight to the emergency department.",
    "{PERSON}, thirty-two, presents with chest tightness after a long flight from {LOCATION}.",
    "Message from {PERSON}: the inhaler has run out and the pharmacy in {LOCATION} has none.",
    "According to {PERSON} the rash started after the holiday in {LOCATION}.",
    "Gave the leaflet to {PERSON}; follow-up booked with {PERSON} in two weeks.",
    "We spoke to the care home in {LOCATION}, and the manager, {PERSON}, confirmed the doses.",
    "{PERSON} asked whether {PERSON} could collect the prescription for her.",
]
HELDOUT_V2_SEED = 2026
# Held-out v3 (2026-10-19), written before the tagger's second training round, whose phrasings were
# written knowing v2: v3 is the unseen set for that round.
HELDOUT_V3_TEMPLATES = [
    "Results were explained over the phone to {PERSON}, who wants a second opinion.",
    "her brother {PERSON} usually brings her in from {LOCATION} on Tuesdays.",
    "Taxi booked to take {PERSON} home to {LOCATION} after discharge.",
    "Letter copied to {PERSON} and to the rheumatology team in {LOCATION}.",
    "No family nearby; {PERSON} is listed as the emergency contact.",
    "She grew up in {LOCATION} and had all her vaccinations there.",
    "Covering doctor tonight is {PERSON}, bleep via switchboard.",
    "{PERSON} reports the same symptoms as her sister {PERSON}.",
    "Previously under the care of the hospital in {LOCATION} for asthma.",
    "Thanks for seeing {PERSON}, a keen cyclist with knee pain.",
]
HELDOUT_V3_SEED = 3031


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


def build(n: int = 200, seed: int = 42, templates: list[str] | None = None) -> list[Snippet]:
    templates = templates or TEMPLATES
    fake = Faker("en_US")
    Faker.seed(seed)
    rng = random.Random(seed)
    snippets = []
    for i in range(n):
        template = templates[i % len(templates)]
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
